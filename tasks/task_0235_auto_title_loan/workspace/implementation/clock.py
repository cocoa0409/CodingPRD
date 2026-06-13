"""Server-held 'current clock time' (PRD 2.10).

All time-gated logic reads this single clock rather than wall-clock time.
A ComplianceAdmin sets it via POST /_clock/set_current_utc.
Before any explicit set, it defaults to the real current time.
"""
from datetime import datetime, timezone

_current = None


def get_now():
    """Return the current clock as a timezone-aware UTC datetime."""
    if _current is not None:
        return _current
    return datetime.now(timezone.utc)


def set_now(dt):
    global _current
    _current = dt
