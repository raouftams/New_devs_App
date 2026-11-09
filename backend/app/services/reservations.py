from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, List
from zoneinfo import ZoneInfo
import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

async def calculate_monthly_revenue(
    property_id: str, tenant_id: str, month: int, year: int, db_session
) -> Decimal:
    """Revenue for a month, using the property's own timezone for month boundaries."""

    # 1. Get the property's timezone (match on BOTH id and tenant_id)
    tz_row = (await db_session.execute(
        text("SELECT timezone FROM properties WHERE id = :pid AND tenant_id = :tid"),
        {"pid": property_id, "tid": tenant_id},
    )).first()
    if not tz_row:
        return Decimal("0.00")

    tz = ZoneInfo(tz_row.timezone)

    # 2. Month boundaries in the property's timezone
    start_date = datetime(year, month, 1, tzinfo=tz)
    end_date = (
        datetime(year + 1, 1, 1, tzinfo=tz)
        if month == 12
        else datetime(year, month + 1, 1, tzinfo=tz)
    )
    logger.debug("Monthly revenue %s/%s from %s to %s", tenant_id, property_id, start_date, end_date)

    # 3. Run the query
    result = await db_session.execute(
        text("""
            SELECT COALESCE(SUM(total_amount), 0) AS total
            FROM reservations
            WHERE property_id = :pid
              AND tenant_id = :tid
              AND check_in_date >= :start_date
              AND check_in_date <  :end_date
        """),
        {"pid": property_id, "tid": tenant_id, "start_date": start_date, "end_date": end_date},
    )
    total = Decimal(str(result.scalar()))
    return total.quantize(Decimal("0.01"))

async def calculate_total_revenue(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Aggregates revenue from database.
    """
    try:
        # Import database pool
        from app.core.database_pool import DatabasePool
        
        # Initialize pool if needed
        db_pool = DatabasePool()
        await db_pool.initialize()
        
        if db_pool.session_factory:
            async with db_pool.session_factory() as session:
                # Use SQLAlchemy text for raw SQL
                from sqlalchemy import text
                query = text("""
                    SELECT 
                        property_id,
                        SUM(total_amount) as total_revenue,
                        COUNT(*) as reservation_count
                    FROM reservations 
                    WHERE property_id = :property_id AND tenant_id = :tenant_id
                    GROUP BY property_id
                """)
                result = await session.execute(query, {
                    "property_id": property_id, 
                    "tenant_id": tenant_id
                })
                row = result.fetchone()
                
                if row:
                    total_revenue = Decimal(str(row.total_revenue))
                    return {
                        "property_id": property_id,
                        "tenant_id": tenant_id,
                        "total": str(total_revenue),
                        "currency": "USD", 
                        "count": row.reservation_count
                    }
                else:
                    # No reservations found for this property
                    return {
                        "property_id": property_id,
                        "tenant_id": tenant_id,
                        "total": "0.00",
                        "currency": "USD",
                        "count": 0
                    }
        else:
            raise Exception("Database pool not available")
            
    except Exception as e:
        print(f"Database error for {property_id} (tenant: {tenant_id}): {e}")
        
