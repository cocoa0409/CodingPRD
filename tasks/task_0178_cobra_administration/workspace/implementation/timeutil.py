"""Date/time helpers — ISO 8601 UTC with millisecond precision, plus calendar
month arithmetic used pervasively by the COBRA timeline calculations.

We deliberately avoid python-dateutil to keep the dependency surface to Flask
alone; all month math is implemented here from the stdlib.
"""
import calendar
from datetime import datetime, timezone, timedelta


def now_iso(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits and a
    trailing 'Z'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 string (or pass through a datetime) into an aware UTC
    datetime. Returns None for None. Raises ValueError on malformed input."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if not isinstance(value, str):
        raise ValueError("not a datetime string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_months(dt, months):
    """Advance a datetime by a whole number of calendar months, clamping the
    day to the last valid day of the target month."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def last_day_of_month(year, month):
    return calendar.monthrange(year, month)[1]


def days_in_month(dt):
    return calendar.monthrange(dt.year, dt.month)[1]


def end_of_month_dt(dt):
    """Return a datetime at the last calendar day of dt's month (00:00:00)."""
    ld = last_day_of_month(dt.year, dt.month)
    return dt.replace(day=ld, hour=0, minute=0, second=0, microsecond=0)


def start_of_month_dt(dt):
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def parse_year_month(s):
    """Parse a 'YYYY-MM' string into (year, month). Raises ValueError if
    malformed."""
    if not isinstance(s, str):
        raise ValueError("coverage_month must be a string")
    parts = s.split("-")
    if len(parts) != 2:
        raise ValueError("coverage_month must be YYYY-MM")
    y, m = parts
    if len(y) != 4 or not y.isdigit() or len(m) != 2 or not m.isdigit():
        raise ValueError("coverage_month must be YYYY-MM")
    yi, mi = int(y), int(m)
    if mi < 1 or mi > 12:
        raise ValueError("coverage_month month out of range")
    return yi, mi


def year_month_index(year, month):
    """Absolute month ordinal for comparing/diffing YYYY-MM tuples."""
    return year * 12 + (month - 1)


def month_diff_inclusive(from_dt, through_dt):
    """(through.year-from.year)*12 + (through.month-from.month) + 1."""
    return ((through_dt.year - from_dt.year) * 12
            + (through_dt.month - from_dt.month) + 1)
