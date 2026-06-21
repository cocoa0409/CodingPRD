"""Server-controlled UTC clock for test-driving (PRD §3.7).

A PlatformAdmin sets the current UTC instant; window-fee bands and the
reclean window are gated off this clock. Until set, it falls back to real
wall-clock UTC so timestamps remain sensible.
"""
from datetime import datetime, timezone


class Clock:
    def __init__(self):
        self._current = None

    def set(self, dt):
        self._current = dt

    def now(self):
        if self._current is not None:
            return self._current
        return datetime.now(timezone.utc)


clock = Clock()
