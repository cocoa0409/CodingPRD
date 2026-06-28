"""Server logical clock.

Default is 2026-04-01T00:00:00Z. It never falls back to wall-clock time.
Settable via POST /_clock/set_current_utc.
"""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = _DEFAULT


def reset():
    global _now
    _now = _DEFAULT


def set_now(dt: datetime):
    global _now
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _now = dt.astimezone(timezone.utc)


def now() -> datetime:
    return _now
