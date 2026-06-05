from datetime import datetime, timezone


class Clock:
    """Logical server clock. None => use real wall clock.

    The test-driving endpoint /_clock/set_current_utc pins this to a fixed
    instant so windows, expiry sweeps and tier years are deterministic.
    """

    def __init__(self):
        self._now = None

    def now(self):
        if self._now is not None:
            return self._now
        return datetime.now(timezone.utc)

    def set(self, dt):
        self._now = dt


clock = Clock()
