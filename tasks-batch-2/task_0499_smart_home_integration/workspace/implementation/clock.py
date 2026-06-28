"""Server-maintained logical clock.

PRD §2.10: At server startup the logical clock reads exactly
2026-01-01T00:00:00Z, and before any clock-setting call it remains at that
default and never falls back to wall-clock time.
"""
from datetime import datetime, timezone

# Fresh process on every start.sh invocation -> default re-applied each boot.
_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": _DEFAULT}


def now():
    """Return the current logical-clock instant (aware UTC datetime)."""
    return _state["now"]


def set_now(dt):
    """Set the logical clock to a supplied aware UTC datetime."""
    _state["now"] = dt
