"""Shared helpers: ids, timestamps, logical clock, calendar arithmetic, rounding."""
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id() -> str:
    """UUID with no type prefix (PRD §2.5)."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def now_ts() -> str:
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.2/§2.5)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def _parse_dt(s: str) -> datetime:
    s = str(s).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # Datetime comparisons at second precision, no fractional microseconds
    return dt.replace(microsecond=0)


def _fmt_dt(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class LogicalClock:
    """Logical clock decoupled from wall-clock time (PRD §2.4)."""

    def __init__(self):
        self._dt = _parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return _fmt_dt(self._dt)

    def today(self) -> date:
        return self._dt.date()

    def set(self, to_iso8601: str) -> datetime:
        self._dt = _parse_dt(to_iso8601)
        return self._dt


CLOCK = LogicalClock()


def clock_now_iso() -> str:
    return CLOCK.now_iso()


def clock_now_ts() -> str:
    """Logical-clock reading rendered with three fractional digits (PRD §2.4/§2.5):
    every system-stamped resource timestamp (created_at, updated_at) reads from
    the logical clock, never the host wall clock."""
    dt = CLOCK.now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_today() -> date:
    return CLOCK.today()


def parse_datetime(s: str) -> datetime:
    return _parse_dt(s)


def fmt_datetime(dt: datetime) -> str:
    return _fmt_dt(dt)


def parse_date(s) -> date:
    if isinstance(s, date):
        return s
    return date.fromisoformat(str(s).strip())


def is_valid_date(s) -> bool:
    if not isinstance(s, str):
        return False
    try:
        date.fromisoformat(s.strip())
        return True
    except (ValueError, TypeError):
        return False


def is_valid_datetime(s) -> bool:
    if not isinstance(s, str):
        return False
    try:
        _parse_dt(s)
        return True
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Decimal rounding helpers — round-half-up throughout (PRD §2.7)
# ---------------------------------------------------------------------------

def D(x) -> Decimal:
    """Exact Decimal coercion; floats go through repr to avoid binary noise."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(repr(x))
    return Decimal(x)


def round_half_up(x, places: int) -> Decimal:
    """Round half-up to `places` decimal places."""
    quantum = Decimal(1).scaleb(-places)  # 10^-places
    return D(x).quantize(quantum, rounding=ROUND_HALF_UP)


def to_number(d: Decimal, places: int):
    """Serialize a Decimal: int when places == 0, else float."""
    if places == 0:
        return int(d)
    return float(d)
