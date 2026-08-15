"""Shared helpers: ids, timestamps, logical clock, calendar arithmetic (PRD 2.4, 2.5, 2.9)."""
import calendar
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone

from errors import raise_error, ERR_CLOCK_REGRESSION


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def now_ts() -> str:
    """Wall-clock ISO 8601 UTC timestamp with three fractional digits (envelope only)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Datetime parsing/formatting for logical-clock comparisons.
# Logical-clock values are second-precision UTC: "YYYY-MM-DDTHH:MM:SSZ".
# ---------------------------------------------------------------------------

def _parse_dt(s: str) -> datetime:
    s = str(s).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0)


def _fmt_dt(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_datetime(s: str) -> datetime:
    return _parse_dt(s)


def fmt_datetime(dt: datetime) -> str:
    return _fmt_dt(dt)


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5): starts at exactly 2026-08-01T00:00:00Z,
# moves strictly forward, never falls back to wall-clock time.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self._dt = _parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return _fmt_dt(self._dt)

    def now_ts(self) -> str:
        """Logical-clock timestamp rendered with three fractional digits.

        Entity created_at/updated_at are 'set at creation' / 'refreshed upon
        every change' (PRD 2.4) against the server's only time source — the
        logical clock (PRD 2.5: 'never falls back to wall-clock time')."""
        return _fmt_dt(self._dt)[:-1] + ".000Z"

    def today(self) -> date:
        return self._dt.date()

    def set(self, to_iso8601: str) -> datetime:
        new_dt = _parse_dt(to_iso8601)
        if new_dt <= self._dt:
            raise_error(ERR_CLOCK_REGRESSION,
                        "clock regression: to_iso8601 must be strictly after the current logical clock")
        self._dt = new_dt
        return self._dt


CLOCK = LogicalClock()


# ---------------------------------------------------------------------------
# Calendar-month arithmetic with day-of-month clamping (PRD 2.9):
# 2026-08-31 minus 6 months = 2026-02-28; 2024-02-29 + 12 months = 2025-02-28.
# ---------------------------------------------------------------------------

def add_months(dt: datetime, months: int) -> datetime:
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    day = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=day)


def sub_months(dt: datetime, months: int) -> datetime:
    return add_months(dt, -months)


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)
