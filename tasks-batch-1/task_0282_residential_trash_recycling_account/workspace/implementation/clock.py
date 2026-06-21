"""Logical server clock.

PRD §3.13: a Dispatcher can set the server's logical clock via
POST /_clock/set_current_utc. The clock drives due-date / collections billing
transitions and the rolling windows used by missed-credit escalation.

When the clock has never been set, real wall-clock UTC is used as the current
instant (the store starts empty on every boot — no seeding).
"""
from datetime import datetime, timezone

_current_utc = None  # type: datetime | None


def now():
    """Return the current logical UTC instant (timezone-aware)."""
    if _current_utc is not None:
        return _current_utc
    return datetime.now(timezone.utc)


def set_now(dt):
    global _current_utc
    _current_utc = dt


def today_date():
    """Current clock instant truncated to UTC midnight (date as datetime)."""
    n = now()
    return datetime(n.year, n.month, n.day, tzinfo=timezone.utc)
