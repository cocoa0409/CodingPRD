"""Logical clock — controllable wall clock for time-gated business rules.

The HTTP response envelope's `api_request_timestamp` uses *wall clock* via
app.response; this clock here is the logical clock used to stamp punches,
to check punch windows, and to drive detention computations. Tests drive it
through /timekeeping/_clock/advance and /timekeeping/_clock/set.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone


def parse_iso_utc(s: str) -> datetime:
    """Parse an ISO-8601 string into a tz-aware UTC datetime.

    Accepts '...Z' and explicit offset forms; naive forms default to UTC."""
    if not isinstance(s, str) or not s:
        raise ValueError("timestamp must be a non-empty ISO 8601 string")
    candidate = s
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    dt = datetime.fromisoformat(candidate)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso_ms(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with three fractional digits + Z."""
    dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


class LogicalClock:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._now: datetime = datetime.now(timezone.utc).replace(microsecond=0)

    def now(self) -> datetime:
        return self._now

    def now_iso(self) -> str:
        return format_iso_ms(self._now)

    def advance(self, seconds: int) -> datetime:
        with self._lock:
            self._now = self._now + timedelta(seconds=int(seconds))
        return self._now

    def set_to(self, iso: str) -> datetime:
        with self._lock:
            self._now = parse_iso_utc(iso)
        return self._now


_CLOCK = LogicalClock()


def get_clock() -> LogicalClock:
    return _CLOCK
