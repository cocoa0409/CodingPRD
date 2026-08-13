"""Logical clock. Starts at 2026-08-01T00:00:00Z; never falls back to wall clock."""
from datetime import datetime, timezone

_state = {
    "current": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
}


def now():
    return _state["current"]


def set_clock(dt):
    _state["current"] = dt
    return _state["current"]
