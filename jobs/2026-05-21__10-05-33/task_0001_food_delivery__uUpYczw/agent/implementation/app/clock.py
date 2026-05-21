"""Logical wall clock.

Time advances naturally with real-world seconds, but `advance(seconds)`
adds an offset so admin-driven simulations can fast-forward without
sleeping. All consumers route through this module so that placement
timestamps, dispatch timeouts, and return windows share one source.
"""
from __future__ import annotations

import datetime
import time


def _now_real() -> float:
    return time.time()


class Clock:
    def __init__(self) -> None:
        self._offset_seconds: float = 0.0

    def now_epoch(self) -> float:
        return _now_real() + self._offset_seconds

    def now_dt(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(self.now_epoch(), tz=datetime.timezone.utc)

    def now_iso(self) -> str:
        return iso(self.now_dt())

    def advance(self, seconds: float) -> None:
        self._offset_seconds += float(seconds)


def iso(dt: datetime.datetime) -> str:
    """ISO 8601 UTC with exactly 3 fractional digits, suffix Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def parse_iso(s: str) -> datetime.datetime:
    # Accept the strict format we emit.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(s)
