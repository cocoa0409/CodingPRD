"""Shared helpers: ids, timestamps, the logical clock, calendar and decimal arithmetic."""
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def parse_dt(s: str) -> datetime:
    """Parse an ISO 8601 instant; naive values are treated as UTC."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt: datetime) -> str:
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class LogicalClock:
    """Server-side logical clock (PRD 2.4). Never the wall clock."""

    def __init__(self):
        self._dt = parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def today(self) -> date:
        return self._dt.date()

    def ts(self) -> str:
        return fmt_ts(self._dt)

    def set(self, dt: datetime):
        self._dt = dt


CLOCK = LogicalClock()


def parse_date_strict(s):
    """Strict YYYY-MM-DD parsing; raises ValueError otherwise."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if not _DATE_RE.match(t):
        raise ValueError("not YYYY-MM-DD")
    return date.fromisoformat(t)


def pdate(s) -> date:
    """Parse a stored ISO date string (or pass through a date)."""
    if isinstance(s, date):
        return s
    return date.fromisoformat(s[:10])


def add_years(d: date, n: int) -> date:
    """Calendrical whole-year addition; Feb 29 clamps to Feb 28."""
    try:
        return d.replace(year=d.year + n)
    except ValueError:
        return d.replace(year=d.year + n, day=28)


def dec(x) -> Decimal:
    """Exact Decimal conversion for JSON numbers (via str, never binary float)."""
    return Decimal(str(x))


def round_cents(d: Decimal) -> int:
    """Round half-up to whole integer cents."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_div_int(a: int, b: int) -> int:
    return -(-int(a) // int(b))
