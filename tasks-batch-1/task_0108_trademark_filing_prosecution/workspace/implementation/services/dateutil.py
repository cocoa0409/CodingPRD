"""Calendar arithmetic for statutory windows (PRD §2.7).

Day-based offsets are counted in whole calendar days. Year-based offsets are
counted in calendar years that preserve the original month and day; when the
target month/day does not exist (Feb 29 -> non-leap year) we clamp to the last
valid day of the target month.
"""

import calendar
import math
from datetime import datetime, timedelta, timezone


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt: datetime, days: int) -> datetime:
    return _to_utc(dt) + timedelta(days=int(days))


def add_years(dt: datetime, years: int) -> datetime:
    """Add N calendar years preserving month/day (clamping Feb 29)."""
    dt = _to_utc(dt)
    new_year = dt.year + int(years)
    last_day = calendar.monthrange(new_year, dt.month)[1]
    new_day = min(dt.day, last_day)
    return dt.replace(year=new_year, day=new_day)


def days_late(submitted_at: datetime, deadline: datetime) -> int:
    """max(0, ceil((submitted_at - deadline) / 1 day)).

    0 when submission is on or before the deadline; otherwise the partial-day
    overrun rounded up to the next whole day.
    """
    submitted_at = _to_utc(submitted_at)
    deadline = _to_utc(deadline)
    delta = submitted_at - deadline
    seconds = delta.total_seconds()
    if seconds <= 0:
        return 0
    return int(math.ceil(seconds / 86400.0))
