"""Server logical clock (PRD 2.9).

On server startup the clock reads exactly 2026-04-01T00:00:00Z, and until it is
explicitly set it remains at that default; it never falls back to wall-clock time.
"""
from datetime import datetime, timezone

# Default startup instant — reset on every process boot.
_DEFAULT = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": _DEFAULT}


def reset():
    _state["now"] = _DEFAULT


def now():
    """Current logical clock instant (aware UTC datetime)."""
    return _state["now"]


def set_now(dt):
    _state["now"] = dt
