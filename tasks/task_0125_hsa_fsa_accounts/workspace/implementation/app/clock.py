"""Logical server clock — drives plan-year resolution, ops-runs, audit timestamps."""
from __future__ import annotations

import datetime as _dt
import threading


class LogicalClock:
    """Monotonic non-decreasing logical clock; default to 2025-01-01T00:00:00Z."""

    def __init__(self, initial: _dt.datetime | None = None) -> None:
        if initial is None:
            initial = _dt.datetime(2025, 1, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)
        if initial.tzinfo is None:
            initial = initial.replace(tzinfo=_dt.timezone.utc)
        self._now: _dt.datetime = initial
        self._lock = threading.Lock()

    def now(self) -> _dt.datetime:
        with self._lock:
            return self._now

    def advance_to(self, to: _dt.datetime) -> _dt.datetime:
        """Advance clock to `to`; return the new logical now. Raises ValueError if non-monotonic."""
        if to.tzinfo is None:
            to = to.replace(tzinfo=_dt.timezone.utc)
        with self._lock:
            if to < self._now:
                raise ValueError("non-monotonic clock advance")
            self._now = to
            return self._now


def format_iso(dt: _dt.datetime) -> str:
    """ISO 8601 UTC with three fractional digits, 'Z' suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    else:
        dt = dt.astimezone(_dt.timezone.utc)
    millis = f"{dt.microsecond // 1000:03d}"
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + millis + "Z"


def parse_iso(value) -> _dt.datetime:
    """Parse an ISO 8601 datetime or date string into a tz-aware UTC datetime.

    Accepts:
        - 'YYYY-MM-DD' (interpreted as midnight UTC)
        - 'YYYY-MM-DDTHH:MM:SS[.fff]Z'
        - 'YYYY-MM-DDTHH:MM:SS[.fff]+00:00'
    Raises ValueError on malformed input.
    """
    if value is None:
        raise ValueError("datetime value required")
    if isinstance(value, _dt.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=_dt.timezone.utc)
        return value.astimezone(_dt.timezone.utc)
    if not isinstance(value, str):
        raise ValueError("datetime must be a string")
    s = value.strip()
    if not s:
        raise ValueError("empty datetime")
    # Date-only form
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        try:
            d = _dt.date.fromisoformat(s)
        except ValueError:
            raise
        return _dt.datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=_dt.timezone.utc)
    # Allow trailing 'Z'
    s_normalized = s.replace("Z", "+00:00") if s.endswith("Z") else s
    try:
        dt = _dt.datetime.fromisoformat(s_normalized)
    except ValueError:
        raise
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc)


def to_date(dt: _dt.datetime) -> _dt.date:
    """Return the UTC calendar date of a datetime."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    else:
        dt = dt.astimezone(_dt.timezone.utc)
    return dt.date()


def age_in_years(birth: _dt.datetime, reference: _dt.datetime) -> int:
    """Whole-year age using month/day comparison (NOT (ref-birth).days/365.25)."""
    b = to_date(birth)
    r = to_date(reference)
    age = r.year - b.year
    if (r.month, r.day) < (b.month, b.day):
        age -= 1
    return age
