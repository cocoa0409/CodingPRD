"""Logical clock. Starts at 2026-01-01T00:00:00Z on every boot."""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = DEFAULT_CLOCK

    def set(self, dt):
        self.now = dt


clock = Clock()
