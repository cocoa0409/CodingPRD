"""Deterministic logical clock (PRD section 2.4).

The server never reads the host wall clock.  Every server-side reference to
"now" resolves against this logical clock, which starts at
2026-08-01T00:00:00Z on a fresh boot and only ever moves when
POST /_clock/set_current_utc says so.
"""

from datetime import datetime, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_NOW}


def now():
    return _state["now"]


def set_now(value):
    _state["now"] = value


def iso(value):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )
