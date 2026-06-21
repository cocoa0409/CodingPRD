"""Server clock. Defaults to real UTC; tests may pin it via /_clock/set_current_utc.

The pinned value is used only for any business logic that needs 'now'. Resource
created_at/updated_at timestamps always use real wall-clock UTC so list ordering
by creation time is monotonic within a test, independent of the pinned clock.
"""
from datetime import datetime, timezone

_override = None  # datetime in UTC, or None


def set_current_utc(dt):
    global _override
    _override = dt


def now():
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)


def reset():
    global _override
    _override = None
