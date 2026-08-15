"""Shared helpers: ids, timestamps, logical clock, calendar arithmetic, rounding."""
import calendar
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def now_ts() -> str:
    """ISO 8601 UTC timestamp with three fractional digits (record-keeping clock)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical server clock (PRD 2.4). Business rules read this, never wall-clock.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def _parse_dt(s: str) -> datetime:
    s = str(s).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_dt(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class LogicalClock:
    def __init__(self):
        self._dt = _parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return _fmt_dt(self._dt)

    def set(self, to_iso8601: str) -> datetime:
        self._dt = _parse_dt(to_iso8601)
        return self._dt


CLOCK = LogicalClock()


def parse_datetime(s: str) -> datetime:
    return _parse_dt(s)


def fmt_datetime(dt: datetime) -> str:
    return _fmt_dt(dt)


def add_calendar_months(dt: datetime, months: int) -> datetime:
    """Calendar-month addition with end-of-month clamping.

    Jan 31 + 1 month -> last day of February, preserving time-of-day.
    """
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    day = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=day)


def round_half_up_int(numer, denom) -> int:
    """round_half_up(numer/denom) to an integer via exact integer arithmetic."""
    numer = int(numer)
    denom = int(denom)
    if denom == 0:
        raise ZeroDivisionError("denom")
    if numer >= 0:
        return (2 * numer + denom) // (2 * denom)
    return -((2 * (-numer) + denom) // (2 * denom))


def dec(value) -> Decimal:
    return Decimal(str(value))


def quantize_half_up(d: Decimal, places: int = 0) -> Decimal:
    q = Decimal(1).scaleb(-places)
    return d.quantize(q, rounding=ROUND_HALF_UP)


def is_int_like(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool))
