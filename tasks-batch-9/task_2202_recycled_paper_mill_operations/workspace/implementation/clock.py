"""Logical clock (PRD §2.9). Reads 2026-08-01T00:00:00Z until explicitly set."""
from datetime import datetime, timezone

DEFAULT_INSTANT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_INSTANT}


def reset():
    _state["now"] = DEFAULT_INSTANT


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt
    return _state["now"]


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt(now())
