"""Server logical UTC clock.

The PRD (§2.11) exposes a test-driving capability that pins "now" to an absolute
instant supplied via POST /library/_clock/set. All time-based rules read the
logical clock through now(). When the clock has never been set, now() falls back
to the real wall clock.

State lives in a module-level dict so a fresh process always starts unpinned —
no seeding, no persistence.
"""

from datetime import datetime, timezone

_state = {"pinned": None}


def set_now(dt):
    """Pin the logical clock to a timezone-aware UTC datetime."""
    _state["pinned"] = dt.astimezone(timezone.utc)
    return _state["pinned"]


def now():
    """Return the current logical UTC instant (pinned if set, else real time)."""
    if _state["pinned"] is not None:
        return _state["pinned"]
    return datetime.now(timezone.utc)


def reset():
    _state["pinned"] = None
