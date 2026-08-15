"""Shared helpers: ids, timestamps, logical clock, calendar arithmetic, decimal rounding."""
import calendar
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


# ---------------------------------------------------------------------------
# Wall-clock timestamps (api_request_timestamp / created_at / updated_at)
# ---------------------------------------------------------------------------

_last_ts = None


def now_ts() -> str:
    """ISO 8601 UTC timestamp with three fractional digits; strictly monotonic
    per process so created_at ascending sort has no ties."""
    global _last_ts
    dt = datetime.now(timezone.utc)
    ts = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    if _last_ts is not None and ts <= _last_ts:
        prev = datetime.strptime(_last_ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        dt = prev + timedelta(milliseconds=1)
        ts = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    _last_ts = ts
    return ts


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4) — drives every date/deadline-sensitive rule.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def parse_iso_datetime(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_valid_iso_datetime(s) -> bool:
    if not isinstance(s, str):
        return False
    try:
        parse_iso_datetime(s)
        return True
    except Exception:
        return False


def fmt_clock_dt(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class LogicalClock:
    def __init__(self):
        self._dt = parse_iso_datetime(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return fmt_clock_dt(self._dt)

    def today(self) -> date:
        return self._dt.date()

    def set(self, to_iso8601: str) -> datetime:
        self._dt = parse_iso_datetime(to_iso8601)
        return self._dt


CLOCK = LogicalClock()


# ---------------------------------------------------------------------------
# Calendar helpers
# ---------------------------------------------------------------------------

def parse_date_strict(s) -> date:
    """Strict YYYY-MM-DD parsing."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    parts = s.split("-")
    if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
        raise ValueError("bad date")
    if not (parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit()):
        raise ValueError("bad date")
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


def is_valid_date(s) -> bool:
    try:
        parse_date_strict(s)
        return True
    except Exception:
        return False


def parse_period_strict(s):
    """Strict YYYY-MM month bucket; returns (year, month)."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    parts = s.split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
        raise ValueError("bad period")
    if not (parts[0].isdigit() and parts[1].isdigit()):
        raise ValueError("bad period")
    y, m = int(parts[0]), int(parts[1])
    if not (1 <= m <= 12):
        raise ValueError("bad period")
    return (y, m)


def is_valid_period(s) -> bool:
    try:
        parse_period_strict(s)
        return True
    except Exception:
        return False


def period_str(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def add_months_dt(dt: datetime, months: int) -> datetime:
    """Calendrical month addition on a datetime (day clamps to month end)."""
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    day = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=day)


def months_elapsed(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)


# ---------------------------------------------------------------------------
# Decimal arithmetic (PRD 2.7): money in integer cents; wRVU round-half-up.
# ---------------------------------------------------------------------------

def dec(v) -> Decimal:
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise ValueError("bool is not a number")
    return Decimal(str(v))


def decimal_places(v) -> int:
    d = Decimal(str(v))
    return max(0, -d.as_tuple().exponent)


def round_half_up_decimal(v: Decimal, places: int) -> Decimal:
    q = Decimal(1).scaleb(-places)
    return v.quantize(q, rounding=ROUND_HALF_UP)


def round_half_up_int(v: Decimal) -> int:
    return int(v.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def f2(v: Decimal) -> float:
    """Decimal -> JSON number pinned to 2 decimal places."""
    return float(round_half_up_decimal(v, 2))
