"""Logical clock — the sole source of 'now' for every stamped timestamp.

PRD §3.11: At startup the clock reads exactly 2026-03-01T00:00:00Z, and before
any clock-setting call it holds that default and never falls back to wall-clock
time.
"""
from datetime import datetime, timezone

# Startup default (PRD §3.11).
_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = _DEFAULT

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = Clock()
