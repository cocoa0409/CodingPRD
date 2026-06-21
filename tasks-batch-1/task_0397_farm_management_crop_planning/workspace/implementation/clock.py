"""Test-driving server clock (PRD §3.10).

The server exposes an administrative clock that a FarmManager can set to a
supplied ISO 8601 instant. All window comparisons (REI, PHI, irrigation due)
and applied_at stamping read from this clock so behavior is deterministic.

When no override is set, the clock returns real UTC now.
"""
from datetime import datetime, timezone

_override = None  # datetime (tz-aware UTC) or None


def now():
    """Return the current server UTC clock as a tz-aware datetime."""
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)


def set_clock(dt):
    global _override
    _override = dt
    return _override


def reset():
    global _override
    _override = None
