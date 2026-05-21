"""Logical clock — backed by a monotonic counter advanced by the
PlatformAdmin /_clock/advance capability. We use a fixed epoch so tests
get deterministic timestamps regardless of host clock.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta


_EPOCH = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self) -> None:
        self._seconds = 0.0
        self._tick = 0  # within-request micro-tick so successive events are ordered

    def now(self) -> datetime:
        # Add the micro-tick (microseconds) so that two events occurring
        # within a single advance window still produce strictly increasing
        # timestamps for ordering.
        self._tick += 1
        return _EPOCH + timedelta(seconds=self._seconds, microseconds=self._tick)

    def now_iso(self) -> str:
        return iso_z(self.now())

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("seconds must be non-negative")
        self._seconds += float(seconds)
        # Reset the tick because we advanced macroscopically.
        self._tick = 0


def iso_z(dt: datetime) -> str:
    """Format a datetime in UTC as ISO 8601 with three fractional digits and a Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime(f"%Y-%m-%dT%H:%M:%S.{ms:03d}Z")


def parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)
