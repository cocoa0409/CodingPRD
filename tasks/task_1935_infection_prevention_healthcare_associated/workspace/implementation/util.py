"""Shared utilities: timestamps, ids, logical clock, datetime helpers."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def now_ts() -> str:
    """ISO 8601 UTC with three fractional digits (wall clock; used for meta/request stamps)."""
    return _fmt_ms(datetime.now(timezone.utc))


def _fmt_ms(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_dt(dt: datetime) -> str:
    return _fmt_ms(dt)


def parse_dt(value, field: str = "timestamp"):
    """Parse an ISO-8601 timestamp into an aware UTC datetime. Raises ValueError on failure."""
    if value is None:
        raise ValueError(f"{field} is required")
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            raise ValueError(f"{field} is not a valid ISO-8601 timestamp")
    else:
        raise ValueError(f"{field} must be an ISO-8601 string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def cal_date(dt: datetime):
    """UTC calendar date of a timestamp."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date()


def midnight_utc(d) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def end_of_day_utc(d) -> datetime:
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Logical clock — governs every time-dependent rule. Default 2026-08-01T00:00:00Z.
# Never falls back to wall clock.
# ---------------------------------------------------------------------------
class LogicalClock:
    def __init__(self):
        self._current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def get(self) -> datetime:
        return self._current

    def set(self, dt: datetime):
        self._current = dt


clock = LogicalClock()
