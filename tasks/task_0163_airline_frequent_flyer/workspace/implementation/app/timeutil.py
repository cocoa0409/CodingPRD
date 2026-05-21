"""Time utilities: ISO 8601 formatting and logical clock for sweeps/expiration."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Optional


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
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt: datetime, months: int) -> datetime:
    """Add *months* calendar months to *dt* (clamping month-end where necessary)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    y = dt.year
    m = dt.month - 1 + months
    y += m // 12
    m = m % 12 + 1
    # Clamp day for shorter months
    import calendar
    last_day = calendar.monthrange(y, m)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=y, month=m, day=day)


def day_of_year(dt: datetime) -> int:
    return dt.timetuple().tm_yday


class LogicalClock:
    """Thread-safe logical clock that can be advanced by /_clock/advance."""

    def __init__(self) -> None:
        self._pinned: Optional[datetime] = None
        self._lock = threading.RLock()

    def now(self) -> datetime:
        with self._lock:
            if self._pinned is not None:
                return self._pinned
            return datetime.now(tz=timezone.utc)

    def advance(self, by_seconds: int) -> datetime:
        with self._lock:
            base = self._pinned if self._pinned is not None else datetime.now(tz=timezone.utc)
            target = base + timedelta(seconds=by_seconds)
            self._pinned = target
            return target

    def set(self, dt: datetime) -> datetime:
        with self._lock:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            self._pinned = dt.astimezone(timezone.utc)
            return self._pinned


clock = LogicalClock()
