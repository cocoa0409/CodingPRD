"""Logical clock. Defaults to 2026-01-01T00:00:00Z on a fresh boot."""
from datetime import datetime, timezone

DEFAULT_NOW = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = DEFAULT_NOW

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = Clock()
