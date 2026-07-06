"""Logical clock. Default 2026-05-01T00:00:00Z before any client sets it."""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = DEFAULT_CLOCK

    def get(self):
        return self.now

    def set(self, dt):
        self.now = dt
