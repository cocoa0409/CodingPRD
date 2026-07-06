"""Logical clock. Default 2026-03-01T00:00:00Z; never falls back to wall-clock."""
from datetime import datetime, timezone

DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = DEFAULT

    def set(self, dt):
        self.now = dt

    def get(self):
        return self.now


clock = Clock()
