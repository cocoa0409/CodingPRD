"""Utility helpers: ids, datetime parsing/formatting, calendar arithmetic."""
import calendar
import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc


def new_id():
    return str(uuid.uuid4())


def parse_dt(value):
    """Parse an ISO 8601 string to an aware UTC datetime at second precision.

    Returns None when the value is not a parseable timestamp string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    # All timestamp comparisons in this system are evaluated at second precision.
    return dt.replace(microsecond=0)


def fmt_dt(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def add_months(dt, months):
    """Calendar-month arithmetic preserving the day of month (clamped)."""
    total = dt.year * 12 + (dt.month - 1) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def add_days(dt, days):
    return dt + timedelta(days=days)
