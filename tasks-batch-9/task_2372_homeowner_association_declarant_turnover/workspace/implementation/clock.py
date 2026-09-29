"""Server-held logical clock (PRD §2.5).

Before any call to set it the clock reads exactly 2026-08-01T00:00:00Z and it
never falls back to the host's wall clock.
"""
from datetime import datetime, timezone

_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": _EPOCH}


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)
    return _state["now"]


def reset():
    _state["now"] = _EPOCH
