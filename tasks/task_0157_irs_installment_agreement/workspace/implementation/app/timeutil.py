"""ISO 8601 UTC time helpers with millisecond precision and a logical clock."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Optional


_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def _format_iso(dt: datetime) -> str:
    """Return ISO 8601 UTC string with three fractional digits and Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}.{ms:03d}Z"


def parse_iso(value: str) -> datetime:
    """Parse ISO 8601 datetime; accept trailing Z. Returns aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    if not _ISO_RE.match(value):
        raise ValueError(f"malformed ISO 8601 timestamp: {value!r}")
    v = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LogicalClock:
    """Monotonically-advanceable logical clock for test determinism.

    `now()` returns the most recent value the clock was advanced to; if never
    advanced, returns real wall-clock time. Advances are monotonic — moving
    backward is allowed (we trust the test driver).
    """

    def __init__(self):
        self._lock = RLock()
        self._current: Optional[datetime] = None

    def now(self) -> datetime:
        with self._lock:
            if self._current is not None:
                return self._current
            return datetime.now(timezone.utc)

    def now_iso(self) -> str:
        return _format_iso(self.now())

    def advance_to(self, target: datetime) -> None:
        with self._lock:
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            else:
                target = target.astimezone(timezone.utc)
            self._current = target


CLOCK = LogicalClock()


def now_iso() -> str:
    return CLOCK.now_iso()


def now() -> datetime:
    return CLOCK.now()


def fmt(dt: datetime) -> str:
    return _format_iso(dt)


def add_years(dt: datetime, years: int) -> datetime:
    """Add a whole number of calendar years to a datetime, leap-year aware.

    If the source date is Feb 29 and the target year has no Feb 29, clamp to Feb 28.
    """
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 in a non-leap target year
        return dt.replace(year=dt.year + years, day=28)


def add_months(dt: datetime, months: int) -> datetime:
    """Add a number of months; clamp to last valid day-of-month if necessary."""
    total = dt.year * 12 + (dt.month - 1) + months
    new_year, new_month_idx = divmod(total, 12)
    new_month = new_month_idx + 1
    # Find the max day-of-month for (new_year, new_month)
    if new_month == 12:
        next_month_first = datetime(new_year + 1, 1, 1, tzinfo=dt.tzinfo)
    else:
        next_month_first = datetime(new_year, new_month + 1, 1, tzinfo=dt.tzinfo)
    last_day = (next_month_first - timedelta(days=1)).day
    new_day = min(dt.day, last_day)
    return dt.replace(year=new_year, month=new_month, day=new_day)


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def end_of_month(dt: datetime) -> datetime:
    """Return the moment at the very end of the month containing dt (last day, 23:59:59.999000 UTC).

    For accrual cycle gating, we use the last instant of the month at millisecond precision.
    """
    year, month = dt.year, dt.month
    if month == 12:
        first_of_next = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        first_of_next = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    eom = first_of_next - timedelta(microseconds=1000)
    return eom


def add_one_month(dt: datetime) -> datetime:
    return add_months(dt, 1)
