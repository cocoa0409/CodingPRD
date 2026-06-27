"""Logical clock. Server startup default is 2026-05-01T00:00:00Z.

Time is governed by a logical clock, not wall-clock. Until an operator advances
it, the clock reads exactly the default. Every 'now' in the spec is evaluated
against this logical clock.
"""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = _DEFAULT

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = Clock()
