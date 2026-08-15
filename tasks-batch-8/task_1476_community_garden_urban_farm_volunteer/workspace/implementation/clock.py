"""The logical clock. The server never reads wall-clock time for domain data.

Startup default is exactly 2026-08-01T00:00:00Z (PRD section 2.5).
"""
from datetime import datetime, timezone

_current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now() -> datetime:
    return _current


def set_current(dt: datetime) -> None:
    global _current
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _current = dt.astimezone(timezone.utc)
