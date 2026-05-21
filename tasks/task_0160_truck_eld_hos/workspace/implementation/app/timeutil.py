"""Time utilities: ISO 8601 formatting, logical clock, timezone handling."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo


def iso_now(dt: Optional[datetime] = None) -> str:
    """Render *dt* (default: now) as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        dt = datetime.now(tz=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp.  Accepts trailing 'Z' or explicit offset."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def local_date_str(dt: datetime, tz_name: str) -> str:
    """Render *dt* (UTC datetime) as YYYY-MM-DD in the given IANA timezone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/New_York")
    return dt.astimezone(tz).strftime("%Y-%m-%d")


def local_midnight_utc(date_str: str, tz_name: str) -> datetime:
    """Return the UTC instant of midnight on *date_str* in *tz_name*."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/New_York")
    y, m, d = (int(x) for x in date_str.split("-"))
    local_midnight = datetime(y, m, d, 0, 0, 0, tzinfo=tz)
    return local_midnight.astimezone(timezone.utc)


def next_local_midnight_utc(date_str: str, tz_name: str) -> datetime:
    """Return the UTC instant of midnight at the *end* of *date_str* in *tz_name*."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/New_York")
    y, m, d = (int(x) for x in date_str.split("-"))
    next_day = datetime(y, m, d, 0, 0, 0, tzinfo=tz) + timedelta(days=1)
    return next_day.astimezone(timezone.utc)


class LogicalClock:
    """Thread-safe logical clock that can be pinned by /_clock/advance."""

    def __init__(self) -> None:
        self._pinned: Optional[datetime] = None
        self._lock = threading.RLock()

    def now(self) -> datetime:
        with self._lock:
            if self._pinned is not None:
                return self._pinned
            return datetime.now(tz=timezone.utc)

    def previous_value(self) -> Optional[datetime]:
        with self._lock:
            return self._pinned

    def advance_to(self, target: datetime) -> datetime:
        with self._lock:
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            target = target.astimezone(timezone.utc)
            self._pinned = target
            return target


clock = LogicalClock()
