"""Server clock — settable via POST /_clock/set (PRD §3.9)."""
from datetime import datetime, timezone

_override = None  # datetime (aware, UTC) or None


def set_clock(dt):
    global _override
    _override = dt


def reset_clock():
    global _override
    _override = None


def now():
    """Current server clock as an aware UTC datetime."""
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)
