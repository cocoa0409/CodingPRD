"""Logical clock (PRD §2.4).

At server startup the logical clock reads exactly 2026-01-01T00:00:00Z, and
until it is explicitly moved it remains at that default and never falls back to
wall-clock time.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = DEFAULT_CLOCK

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = LogicalClock()


def reset_clock():
    clock.set(DEFAULT_CLOCK)
