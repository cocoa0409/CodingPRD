"""Logical clock. Only moves forward via POST /_clock/advance.

PRD §2.11. The initial value is the wall-clock UTC at process start so that any
seeded "future" timestamps in tests (which use real wall-clock UTC) make sense.
"""

from datetime import datetime, timezone


def _truncate_to_ms(dt: datetime) -> datetime:
    """Truncate microseconds to millisecond precision.

    PRD §2.4 mandates three-fractional-digit ISO 8601 timestamps. We
    truncate the internal datetime to match so that a value
    round-tripped through iso_format → parse_iso compares equal to the
    original. Without this, sub-millisecond drift breaks boundary
    comparisons (e.g., scheduled_start == deadline_at).
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    micro = (dt.microsecond // 1000) * 1000
    return dt.replace(microsecond=micro)


class Clock:
    def __init__(self):
        self._now = _truncate_to_ms(datetime.now(timezone.utc))

    def now(self) -> datetime:
        return self._now

    def now_iso(self) -> str:
        """ISO 8601 UTC with 3 fractional digits and trailing Z."""
        n = self._now
        # Ensure tz-aware UTC
        if n.tzinfo is None:
            n = n.replace(tzinfo=timezone.utc)
        else:
            n = n.astimezone(timezone.utc)
        return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"

    def advance_to(self, target: datetime) -> bool:
        """Advance forward only. Returns False if target < current."""
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        else:
            target = target.astimezone(timezone.utc)
        target = _truncate_to_ms(target)
        if target < self._now:
            return False
        self._now = target
        return True


CLOCK = Clock()
