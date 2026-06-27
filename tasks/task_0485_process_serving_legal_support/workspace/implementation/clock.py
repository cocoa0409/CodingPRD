"""Logical clock.

Per PRD 2.8: the system operates on a logical clock rather than wall-clock
time. At startup the clock reads exactly 2026-01-01T00:00:00Z, and before any
clock-setting call it returns precisely that default and never falls back to the
host wall clock. All computed timestamps read from this logical clock.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = DEFAULT_CLOCK

    def reset(self):
        self.now = DEFAULT_CLOCK

    def set(self, dt):
        self.now = dt

    def get(self):
        return self.now


clock = Clock()
