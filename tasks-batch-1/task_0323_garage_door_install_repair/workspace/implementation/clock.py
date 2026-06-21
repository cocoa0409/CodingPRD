"""Server notion of current UTC time.

PRD §3.13: the platform exposes an administrative capability that sets the
server's notion of the current UTC instant. Expiry and surcharge banding both
depend on this clock. Default is the real wall clock.
"""
from datetime import datetime, timezone

_override = None  # type: datetime | None


def now():
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)


def set_now(dt):
    global _override
    _override = dt


def reset():
    global _override
    _override = None
