"""Logical clock (PRD §2.4).

Authoritative "now" for every time-dependent rule. At server startup the clock
reads exactly 2026-03-01T00:00:00Z and stays there until an admin moves it via
POST /_clock/set_current_utc. It never falls back to host wall-clock time.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = DEFAULT_CLOCK

    def get(self) -> datetime:
        return self.now

    def set(self, dt: datetime) -> datetime:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self.now = dt.astimezone(timezone.utc)
        return self.now


clock = Clock()
