"""Logical clock.

Per PRD 2.4 every temporal decision in this service runs on a logical clock that
starts at the mandatory default instant 2026-08-01T00:00:00Z and is only moved by
POST /_clock/set_current_utc.
"""
from datetime import datetime, timedelta, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_NOW}


def now():
    return _state["now"]


def set_now(value):
    _state["now"] = value


def reset():
    _state["now"] = DEFAULT_NOW


def to_iso(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    return "%s.%03dZ" % (value.strftime("%Y-%m-%dT%H:%M:%S"), value.microsecond // 1000)


def parse_iso(text):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
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
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def plus_minutes(value, minutes):
    return value + timedelta(minutes=minutes)


def plus_hours(value, hours):
    return value + timedelta(hours=hours)


def plus_days(value, days):
    return value + timedelta(days=days)
