"""The service's logical clock (PRD 2.5).

Before the clock-setting capability is ever called the logical clock reads
exactly 2026-08-01T00:00:00Z; it never falls back to wall time.
"""
from datetime import datetime, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_NOW}


def now():
    return _state["now"]


def set_now(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _state["now"] = dt.astimezone(timezone.utc)


def reset():
    _state["now"] = DEFAULT_NOW


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return fmt(now())
