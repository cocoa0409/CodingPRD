"""Server logical clock.

PRD 2.4: On server startup the clock reads exactly 2026-01-01T00:00:00Z, and
before any clock-setting call it stays at that default and never falls back to
real time.
"""
from datetime import datetime, timezone

# Default startup instant — wiped/reset on every process boot.
_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": _DEFAULT}


def reset():
    _state["now"] = _DEFAULT


def now():
    """Current logical clock instant (aware UTC datetime)."""
    return _state["now"]


def set_now(dt):
    _state["now"] = dt
