"""Calendar arithmetic for months / years / half-years.

USPTO deadlines hit the same day of the month N months out. When the target
month has no such day (e.g. Jan 31 + 1 month), we clamp to the last day of the
target month. Time-of-day is preserved.
"""

from datetime import datetime, timezone
import calendar


def add_months(dt: datetime, months: int) -> datetime:
    """Return a UTC datetime shifted by N calendar months."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    total = (dt.year * 12 + (dt.month - 1)) + int(months)
    new_year, new_month0 = divmod(total, 12)
    new_month = new_month0 + 1
    last_day_of_target = calendar.monthrange(new_year, new_month)[1]
    new_day = min(dt.day, last_day_of_target)
    return dt.replace(year=new_year, month=new_month, day=new_day)


def add_years(dt: datetime, years: int) -> datetime:
    return add_months(dt, int(years) * 12)


def add_half_years(dt: datetime, halves: int) -> datetime:
    """Add N half-years (6 months each)."""
    return add_months(dt, int(halves) * 6)
