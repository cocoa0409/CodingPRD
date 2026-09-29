"""Logical clock (PRD 2.4).

Nothing in this system reads the host machine's wall clock.  The value at
server start is 2026-08-01T00:00:00Z.  Setting the clock is deliberately
inert: no entity is recomputed as a side effect.
"""
from datetime import datetime, timedelta, timezone

DEFAULT_CURRENT_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_CURRENT_UTC}


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)
    return _state["now"]


def reset():
    _state["now"] = DEFAULT_CURRENT_UTC


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse(value):
    """Parse an ISO 8601 instant.  Raises ValueError when unparseable."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not a datetime string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def plus_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def plus_seconds(dt, seconds):
    return dt + timedelta(seconds=seconds)


def local_parts(dt, timezone_offset_minutes):
    """Return (local_minute_of_day, local_day_of_week) with Monday == 0."""
    local = dt + timedelta(minutes=timezone_offset_minutes)
    return local.hour * 60 + local.minute, local.weekday()
