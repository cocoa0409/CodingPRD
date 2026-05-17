"""Logical clock — drives all date-sensitive logic."""
from __future__ import annotations

from datetime import date, datetime, timezone
from threading import Lock


class LogicalClock:
    """A test-driveable logical clock.

    `current_date` is the calendar date used for business logic. `now()`
    returns a UTC timestamp anchored to the current logical date.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._current_dt: datetime | None = None

    def _ensure(self) -> datetime:
        if self._current_dt is None:
            self._current_dt = datetime.now(tz=timezone.utc)
        return self._current_dt

    @property
    def current_date(self) -> date:
        with self._lock:
            return self._ensure().date()

    def now(self) -> datetime:
        with self._lock:
            cur = self._ensure()
        # Add a small offset from wall clock for monotonicity within a logical day.
        wall = datetime.now(tz=timezone.utc)
        return datetime(
            year=cur.year,
            month=cur.month,
            day=cur.day,
            hour=wall.hour,
            minute=wall.minute,
            second=wall.second,
            microsecond=wall.microsecond,
            tzinfo=timezone.utc,
        )

    def set_iso(self, iso_str: str) -> datetime:
        # Accept either YYYY-MM-DD or full ISO 8601
        if "T" in iso_str:
            # full datetime
            s = iso_str
            # Handle "Z" suffix
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
        else:
            dt = datetime.strptime(iso_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        with self._lock:
            self._current_dt = dt
            return dt

    def reset(self) -> None:
        with self._lock:
            self._current_dt = None


clock = LogicalClock()


def now() -> datetime:
    return clock.now()


def now_iso() -> str:
    return iso_format(clock.now())


def iso_format(dt: datetime | None) -> str | None:
    """ISO 8601 UTC with 3 fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def current_date() -> date:
    return clock.current_date


def date_iso(d: date | None) -> str | None:
    if d is None:
        return None
    return d.isoformat()


def parse_iso_date_str(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()
