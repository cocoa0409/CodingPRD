"""ISO 8601 UTC formatting/parsing with three fractional digits (PRD §2.4)."""
from datetime import datetime, timedelta, timezone


def iso(dt):
    """Render a datetime as an ISO 8601 UTC string with exactly 3 fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO 8601 string into an aware UTC datetime; None when unparseable."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def plus_days(dt, days):
    return dt + timedelta(days=days)
