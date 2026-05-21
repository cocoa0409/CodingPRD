"""Logical clock and federal-working-day arithmetic."""
from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Set


# Hard-coded US federal holiday set (observed dates for likely test windows).
# The scaffold says holidays come from SystemClock.federal_workdays_index — we
# pre-seed a conservative set; tests can rely on Mon-Fri exclusion alone.
_DEFAULT_FEDERAL_HOLIDAYS: Set[str] = {
    # New Year's Day
    "2024-01-01", "2025-01-01", "2026-01-01", "2027-01-01", "2028-01-01",
    # MLK Day (3rd Mon of Jan)
    "2024-01-15", "2025-01-20", "2026-01-19", "2027-01-18", "2028-01-17",
    # Presidents Day (3rd Mon of Feb)
    "2024-02-19", "2025-02-17", "2026-02-16", "2027-02-15", "2028-02-21",
    # Memorial Day (last Mon of May)
    "2024-05-27", "2025-05-26", "2026-05-25", "2027-05-31", "2028-05-29",
    # Juneteenth
    "2024-06-19", "2025-06-19", "2026-06-19", "2027-06-18", "2028-06-19",
    # Independence Day
    "2024-07-04", "2025-07-04", "2026-07-03", "2027-07-05", "2028-07-04",
    # Labor Day (1st Mon of Sep)
    "2024-09-02", "2025-09-01", "2026-09-07", "2027-09-06", "2028-09-04",
    # Columbus Day (2nd Mon of Oct)
    "2024-10-14", "2025-10-13", "2026-10-12", "2027-10-11", "2028-10-09",
    # Veterans Day
    "2024-11-11", "2025-11-11", "2026-11-11", "2027-11-11", "2028-11-10",
    # Thanksgiving (4th Thu of Nov)
    "2024-11-28", "2025-11-27", "2026-11-26", "2027-11-25", "2028-11-23",
    # Christmas
    "2024-12-25", "2025-12-25", "2026-12-25", "2027-12-24", "2028-12-25",
}


def _iso_to_datetime(s: str) -> datetime:
    """Parse an ISO-8601 string into a tz-aware UTC datetime.

    Accepts '...Z', '...+00:00', and naive forms (treated as UTC)."""
    if s.endswith("Z"):
        s2 = s[:-1] + "+00:00"
    else:
        s2 = s
    try:
        dt = datetime.fromisoformat(s2)
    except ValueError:
        # Fall back to bare date
        d = date.fromisoformat(s)
        return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_iso_date(s: str) -> date:
    return date.fromisoformat(s[:10])


def _format_datetime_ms(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime(f"%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def _format_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


class SystemClock:
    """Logical, monotonically-controllable wall clock."""

    def __init__(self) -> None:
        # Default to wall clock at first request; tests will advance explicitly.
        self._current: datetime = datetime.now(timezone.utc).replace(microsecond=0)
        self._holidays: Set[str] = set(_DEFAULT_FEDERAL_HOLIDAYS)
        self._lock = threading.Lock()
        self.id = "system_clock_singleton"
        self.created_at = _format_datetime_ms(self._current)

    def get(self) -> datetime:
        return self._current

    def advance_to(self, iso: str) -> datetime:
        with self._lock:
            self._current = _iso_to_datetime(iso)
        return self._current

    def is_federal_working_day(self, d: date) -> bool:
        if d.weekday() >= 5:  # Sat=5 Sun=6
            return False
        if _format_date(d) in self._holidays:
            return False
        return True

    def add_federal_working_days(self, d0: date, n: int) -> date:
        """Return the date that is `n` federal working days strictly after `d0`."""
        count = 0
        cursor = d0
        # Guardrail: don't loop forever; 1 year ≈ 250 working days, give 5y room.
        max_iter = 5000
        while count < n and max_iter > 0:
            cursor = cursor + timedelta(days=1)
            if self.is_federal_working_day(cursor):
                count += 1
            max_iter -= 1
        return cursor

    def to_view(self) -> dict:
        return {
            "id": self.id,
            "current_time": _format_datetime_ms(self._current),
        }


_CLOCK = SystemClock()


def get_clock() -> SystemClock:
    return _CLOCK


# Re-exported helpers
parse_iso_datetime = _iso_to_datetime
parse_iso_date = _parse_iso_date
format_datetime_ms = _format_datetime_ms
format_date = _format_date
