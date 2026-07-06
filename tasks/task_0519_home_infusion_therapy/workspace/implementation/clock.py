"""Logical clock (PRD §2.4). Startup default is 2026-05-01T00:00:00Z and never
falls back to wall-clock time. set_current_utc advances it."""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = _DEFAULT

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt

    def iso(self):
        # ISO 8601 UTC with exactly three fractional digits, Z suffix.
        return format_iso(self._now)


def format_iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


clock = Clock()
