"""Logical clock (PRD §2.5). All business timing reads this clock, never the
wall clock. Default before any advance: exactly 2026-05-01T00:00:00Z.

Entity timestamps (created_at/updated_at) and request-envelope timestamps are
stamped from this clock with a monotonic-millisecond guard so that ordering
by created_at is deterministic within a process.
"""
from datetime import datetime, timezone

_DEFAULT_NOW = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = _DEFAULT_NOW
        self._last_stamp_ms = -1

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt

    def stamp_iso(self):
        """Current logical time as ISO 8601 UTC with three fractional digits,
        strictly increasing across successive calls."""
        ms = int(self._now.timestamp() * 1000)
        if ms <= self._last_stamp_ms:
            ms = self._last_stamp_ms + 1
        self._last_stamp_ms = ms
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


CLOCK = LogicalClock()


def iso_from_dt(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return CLOCK.stamp_iso()
