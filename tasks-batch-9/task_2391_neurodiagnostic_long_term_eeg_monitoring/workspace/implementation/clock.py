"""The server's logical UTC clock (PRD 2.4).

The clock never reads host wall time.  Its value at process startup is exactly
2026-08-01T00:00:00Z and it only moves through POST /_clock/set_current_utc.
All datetimes are handled as naive UTC ``datetime`` objects.
"""
from datetime import datetime, timedelta

EPOCH = datetime(2026, 8, 1, 0, 0, 0)

_now = EPOCH


def now():
    return _now


def set_now(value):
    global _now
    _now = value


def reset():
    global _now
    _now = EPOCH


def iso(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def parse(text):
    """Parse an ISO 8601 instant into a naive UTC datetime, or return None."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = (parsed - parsed.utcoffset()).replace(tzinfo=None)
    return parsed


def plus_minutes(value, minutes):
    return value + timedelta(minutes=minutes)


def plus_hours(value, hours):
    return value + timedelta(hours=hours)


def plus_days(value, days):
    return value + timedelta(days=days)
