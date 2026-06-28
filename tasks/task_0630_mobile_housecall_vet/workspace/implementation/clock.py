"""Logical clock.

Per PRD §2.10: at server startup the clock reads exactly 2026-01-01T00:00:00Z,
and until explicitly moved it never falls back to the host's wall clock.
"""
from datetime import datetime, timezone

# The single mutable logical-clock instant for this process.
_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_state = {"now": _DEFAULT}


def now():
    """Return the current logical-clock instant (timezone-aware UTC)."""
    return _state["now"]


def set_now(dt):
    """Set the logical clock to the given timezone-aware UTC datetime."""
    _state["now"] = dt
