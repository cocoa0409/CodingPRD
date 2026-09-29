"""The server-side logical clock (PRD §2.4).

Startup value is exactly 2026-08-01T00:00:00Z and it never falls back to wall
clock time.  Every `logical clock now` reference in the PRD reads this.
"""
from datetime import datetime, timezone, timedelta

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_CLOCK}


def now():
    return _state["now"]


def set_now(instant):
    _state["now"] = instant.astimezone(timezone.utc)
    return _state["now"]


def reset():
    _state["now"] = DEFAULT_CLOCK


def iso(dt):
    """ISO 8601 UTC with exactly three fractional second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_datetime(value):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def plus_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def plus_days(dt, days):
    return dt + timedelta(days=days)


def floor_minutes(delta):
    """Whole minutes of a timedelta, partial minute discarded (floor)."""
    return int(delta.total_seconds() // 60)
