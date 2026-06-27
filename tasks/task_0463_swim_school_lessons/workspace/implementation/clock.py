"""Logical clock. PRD 2.4: at startup the clock reads exactly 2026-01-01T00:00:00Z
and until an operator advances it, every read of 'the current instant' returns that
default — the server never falls back to real-world time."""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.current = DEFAULT_CLOCK

    def now(self):
        return self.current

    def set(self, dt):
        self.current = dt


clock = Clock()
