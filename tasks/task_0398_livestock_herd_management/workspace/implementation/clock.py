"""Controllable logical UTC clock.

The system exposes POST /_clock/set_current_utc to set the current instant.
Until set, the clock defaults to the real wall-clock UTC time. All date
comparisons in the system are done at *date* granularity in UTC.
"""
from datetime import datetime, timezone


class Clock:
    def __init__(self):
        self._now = None  # None => use real time

    def reset(self):
        self._now = None

    def set(self, dt):
        # dt is a timezone-aware datetime in UTC
        self._now = dt

    def now(self):
        if self._now is not None:
            return self._now
        return datetime.now(timezone.utc)

    def today(self):
        """Current clock date (a datetime.date) in UTC."""
        return self.now().date()


clock = Clock()
