"""Shared helpers: ids, timestamps, logical clock, calendar arithmetic, decimal rounding.

PRD §2.4: every deadline/window/timestamp comparison runs on the server-side
logical clock, which starts at exactly 2026-08-01T00:00:00Z and never falls
back to wall-clock time. System-stamped resource fields read from the logical
clock; the envelope's api_request_timestamp is wall-clock with 3 fractional
digits (PRD §2.2).
"""
import calendar
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING


def new_id() -> str:
    """UUID with no type prefix (PRD §2.5)."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def now_ts() -> str:
    """Wall-clock ISO 8601 UTC with three fractional digits (envelope meta)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def parse_dt(s) -> datetime:
    """Parse an ISO 8601 date or datetime; naive values are treated as UTC;
    result normalized to second precision in UTC."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if not t:
        raise ValueError("empty datetime")
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def fmt_dt(dt: datetime) -> str:
    """Second-precision UTC rendering used for all logical-clock stamps."""
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_valid_dt(s) -> bool:
    if not isinstance(s, str):
        return False
    try:
        parse_dt(s)
        return True
    except (ValueError, TypeError):
        return False


class LogicalClock:
    """Server-side logical clock (PRD §2.4). Fixed default; moved only by
    POST /api/_clock/set_current_utc."""

    def __init__(self):
        self._dt = parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return fmt_dt(self._dt)

    def set(self, to_iso8601: str) -> datetime:
        self._dt = parse_dt(to_iso8601)
        return self._dt


CLOCK = LogicalClock()


def clock_stamp() -> str:
    """Logical-clock reading stamped onto resources (created_at, updated_at,
    invited_at, decided_at, ...)."""
    return CLOCK.now_iso()


# ---------------------------------------------------------------------------
# Calendar arithmetic (PRD §2.8, calculation mandatory_review_date)
# ---------------------------------------------------------------------------

def add_months(d: date, months: int) -> date:
    """Calendrical month addition, month-anchored with day clamping."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def dt_to_date(dt: datetime) -> date:
    return dt.astimezone(timezone.utc).date()


# ---------------------------------------------------------------------------
# Decimal helpers — round-half-up throughout (PRD §2.10)
# ---------------------------------------------------------------------------

def D(x) -> Decimal:
    """Exact Decimal coercion; floats go through repr to avoid binary noise."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(repr(x))
    if isinstance(x, bool):
        return Decimal(int(x))
    return Decimal(x)


def round_half_up(x, places: int) -> Decimal:
    return D(x).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def ceil_decimal(x) -> int:
    return int(D(x).to_integral_value(rounding=ROUND_CEILING))


def as_number(x):
    """Serialize a computed Decimal as a plain JSON number."""
    if x is None:
        return None
    if isinstance(x, Decimal):
        return float(x)
    return x
