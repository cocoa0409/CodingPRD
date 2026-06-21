"""Deterministic logical clock (PRD 2.5).

Timing is read from a server-controlled logical clock, not wall time, so all
stamps (ordered_at_utc, delivered_at_utc, requested_at_utc, expires_at_utc) are
reproducible. A PlatformAdmin advances it via POST /_clock/set_current_utc.
"""
from datetime import datetime, timezone

# In-memory module-global; reset on every fresh process (per-test-server boot).
_now = None  # datetime in UTC, or None meaning "follow wall clock"


def set_now(dt):
    global _now
    _now = dt


def now():
    """Return the current logical instant as a timezone-aware UTC datetime."""
    if _now is not None:
        return _now
    return datetime.now(timezone.utc)


def reset():
    global _now
    _now = None
