"""Server logical clock and timestamp formatting.

The server maintains a logical clock used for all timestamp stamping and for
eligibility recomputation (PRD 2.9 / 3.10). A test-driving capability sets it.
When the clock has not been set, fall back to real wall-clock UTC.
"""
from datetime import datetime, timezone


class Clock:
    def __init__(self):
        self._now = None  # type: datetime | None

    def set(self, dt):
        """dt is a timezone-aware datetime in UTC."""
        self._now = dt

    def now(self):
        if self._now is not None:
            return self._now
        return datetime.now(timezone.utc)


# Module-level singleton clock for this process.
clock = Clock()


def iso_z(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso_z(clock.now())
