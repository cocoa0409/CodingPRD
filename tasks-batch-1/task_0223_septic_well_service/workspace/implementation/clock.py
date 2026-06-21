"""Server logical clock.

Drives cooling-off and due-date logic deterministically. Defaults to real wall
clock; the test-driving endpoint POST /_clock/set_current_utc overrides it.
"""
from datetime import datetime, timezone


class Clock:
    def __init__(self):
        self._override = None  # datetime (tz-aware) or None

    def now(self):
        if self._override is not None:
            return self._override
        return datetime.now(timezone.utc)

    def set(self, dt):
        self._override = dt


clock = Clock()
