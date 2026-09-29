"""ISO-8601 UTC parsing / formatting (PRD Section 2.2, 2.4)."""
from datetime import datetime, timezone, timedelta

DAY = timedelta(days=1)


def parse_iso(value):
    """Parse an ISO-8601 UTC timestamp. Returns an aware UTC datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def add_days(dt, days):
    return dt + timedelta(days=days)


def floor_day_diff(later, earlier):
    """floor((later - earlier) / 1 day) as an integer.

    timedelta normalises so that 0 <= seconds < 86400 and 0 <= microseconds,
    which makes ``.days`` already the mathematical floor of the day quotient.
    """
    return (later - earlier).days
