"""Logical clock — drives all date-sensitive logic per PRD §2.10."""
from __future__ import annotations

from datetime import date, datetime, timezone
from threading import Lock


class LogicalClock:
    """A test-driveable logical clock.

    `current_date` is the calendar date used for business logic. `clock_year`
    is derived from it. `now()` returns a UTC timestamp anchored to noon on
    the current_date so timestamps remain monotonically meaningful as the
    date advances.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._current_date: date | None = None
        # When True, now() returns wall clock; when False, anchored to current_date.
        # We always anchor to a logical date to make tests deterministic.

    def _ensure(self) -> date:
        if self._current_date is None:
            self._current_date = datetime.now(tz=timezone.utc).date()
        return self._current_date

    @property
    def current_date(self) -> date:
        with self._lock:
            return self._ensure()

    @property
    def clock_year(self) -> int:
        with self._lock:
            return self._ensure().year

    def now(self) -> datetime:
        """Return a UTC timestamp anchored to the current logical date.

        We add a small monotonic offset within a logical day by leaning on
        the wall clock's sub-second component. The date portion is the
        logical date, the time portion is "now"'s time-of-day.
        """
        with self._lock:
            cur = self._ensure()
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

    def advance_days(self, days: int) -> date:
        from datetime import timedelta

        with self._lock:
            cur = self._ensure()
            new = cur + timedelta(days=days)
            self._current_date = new
            return new

    def set_date(self, new_date: date) -> date:
        with self._lock:
            self._current_date = new_date
            return new_date

    def reset(self) -> None:
        with self._lock:
            self._current_date = None


clock = LogicalClock()


def now() -> datetime:
    return clock.now()


def now_iso() -> str:
    return iso_format(clock.now())


def iso_format(dt: datetime | None) -> str | None:
    """ISO 8601 UTC with 3 fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
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


def current_year() -> int:
    return clock.clock_year


def date_iso(d: date | None) -> str | None:
    if d is None:
        return None
    return d.isoformat()


def parse_date_str(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()
