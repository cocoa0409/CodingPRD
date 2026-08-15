"""Shared helpers: ids, timestamps, the logical clock, calendar arithmetic."""
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def _wall_ts() -> str:
    """Wall-clock ISO 8601 UTC timestamp with three fractional digits (meta only)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4): never falls back to wall-clock; forward-only.
# ---------------------------------------------------------------------------

def _parse_dt(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt: datetime) -> str:
    """ISO 8601 UTC with exactly three fractional digits (entity timestamps)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_dt_seconds(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return fmt_ts(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class LogicalClock:
    """Startup default reads exactly 2026-08-01T00:00:00Z (PRD 2.4)."""

    def __init__(self):
        self._dt = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return fmt_ts(self._dt)

    def today(self) -> date:
        return self._dt.date()

    def current_utc_display(self) -> str:
        return fmt_dt_seconds(self._dt)

    def set(self, to_iso8601: str) -> datetime:
        new_dt = _parse_dt(to_iso8601)
        if new_dt < self._dt:
            from errors import raise_error, ERR_INVALID_REQUEST
            raise_error(ERR_INVALID_REQUEST,
                        "the logical clock moves forward only")
        self._dt = new_dt
        return self._dt


CLOCK = LogicalClock()


def parse_datetime(s: str) -> datetime:
    return _parse_dt(s)


def parse_date(s: str) -> date:
    return date.fromisoformat(s.strip())


def week_start_of(dt: datetime) -> datetime:
    """Monday 00:00:00.000Z of the logical week containing dt."""
    d = dt.date()
    monday = d - timedelta(days=d.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)
