"""Datetime parsing and arithmetic helpers.

All datetimes are timezone-aware UTC. ISO-8601 inputs may carry a trailing 'Z'.
"""
import calendar
from datetime import datetime, timezone


def parse_iso(value):
    """Parse an ISO-8601 string into an aware UTC datetime. Returns None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    """Advance dt by a whole number of calendar months (clamping day overflow)."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def end_of_month(dt):
    """Return dt set to the last calendar day of its month (time-of-day preserved)."""
    last_day = calendar.monthrange(dt.year, dt.month)[1]
    return dt.replace(day=last_day)


def whole_days(start, end):
    """Whole days in the half-open interval [start, end). Negative clamped to 0."""
    if end <= start:
        return 0
    delta = end - start
    return delta.days  # timedelta.days is the floor of total days
