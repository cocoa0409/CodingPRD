from datetime import datetime, timezone


class Clock:
    """Logical clock the test harness drives via POST /_clock/set_current_utc.

    None => fall back to real wall-clock time. Once set, every read returns the
    pinned instant so acquired_at / disposed_at / wash-sale windows / tax-year
    gates are deterministic.
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
