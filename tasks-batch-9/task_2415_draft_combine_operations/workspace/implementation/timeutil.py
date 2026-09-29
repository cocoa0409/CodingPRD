"""ISO-8601 helpers. All datetimes are timezone-aware UTC internally."""

from datetime import datetime, timedelta, timezone


def parse_iso(value):
    """Parse an ISO 8601 instant. Raises ValueError on anything unusable."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """Format as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
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


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def add_days(dt, days):
    return dt + timedelta(days=days)


def whole_minutes_between(start, end):
    return int((end - start).total_seconds() // 60)
