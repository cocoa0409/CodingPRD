"""Logical-clock time helpers. Nothing here consults the host wall clock."""
import calendar
from datetime import datetime, timedelta, timezone

UTC = timezone.utc


def parse_dt(value):
    """Parse an ISO-8601 instant. Raises ValueError when unparseable."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if not s:
        raise ValueError("empty")
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def add_months(dt, months):
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_years(dt, years):
    return add_months(dt, 12 * years)


def whole_days(start, end):
    """Whole days from start to end; may be negative."""
    return int((end - start).total_seconds() // 86400)
