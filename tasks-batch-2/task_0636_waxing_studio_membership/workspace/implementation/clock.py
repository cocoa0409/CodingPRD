"""Logical clock.

PRD 2.10: At server startup the clock reads exactly 2026-01-01T00:00:00Z, and
before any operator sets it the clock continues to read that exact default — it
never falls back to real wall-clock time.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = DEFAULT_CLOCK

    def reset(self):
        self.now = DEFAULT_CLOCK

    def get(self):
        return self.now

    def set(self, dt):
        self.now = dt


clock = Clock()
