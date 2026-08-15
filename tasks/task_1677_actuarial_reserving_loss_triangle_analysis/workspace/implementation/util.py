"""Shared helpers: ids, timestamps, logical clock, quarter arithmetic, Decimal rounding."""
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def now_ts() -> str:
    """ISO 8601 UTC timestamp with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock — default 2026-08-01T00:00:00Z per PRD §2.5
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def _parse_dt(s: str) -> datetime:
    s = s.strip()
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


class LogicalClock:
    def __init__(self):
        self._dt = _parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return _fmt_dt(self._dt)

    def today(self) -> date:
        return self._dt.date()

    def set(self, to_iso8601: str) -> datetime:
        new_dt = _parse_dt(to_iso8601)
        # PRD does not mandate monotonicity; accept any well-formed ISO instant.
        self._dt = new_dt
        return self._dt


CLOCK = LogicalClock()


def parse_datetime(s: str) -> datetime:
    return _parse_dt(s)


def parse_date(s: str) -> date:
    return date.fromisoformat(s.strip())


def fmt_datetime(dt: datetime) -> str:
    return _fmt_dt(dt)


# ---------------------------------------------------------------------------
# Quarter label helpers — "YYYY-Qn"
# ---------------------------------------------------------------------------

QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")


def is_valid_quarter(s) -> bool:
    if not isinstance(s, str):
        return False
    return QUARTER_RE.match(s) is not None


def quarter_of_date(d: date) -> str:
    q = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{q}"


def quarter_of_datetime_str(s: str) -> str:
    dt = parse_datetime(s)
    return quarter_of_date(dt.date())


def quarter_index(q: str) -> int:
    """Linear index so quarter labels compare chronologically; works with YYYY-Qn."""
    m = QUARTER_RE.match(q)
    year, n = int(m.group(1)), int(m.group(2))
    return year * 4 + (n - 1)


def quarter_diff(from_q: str, to_q: str) -> int:
    """Number of quarters elapsed from from_q to to_q (>= 0 when to_q >= from_q)."""
    return quarter_index(to_q) - quarter_index(from_q)


def prev_quarter(q: str) -> str:
    idx = quarter_index(q) - 1
    year, off = divmod(idx, 4)
    return f"{year}-Q{off + 1}"


# ---------------------------------------------------------------------------
# Decimal rounding helpers — pinned 4dp half-up per PRD §2.6
# ---------------------------------------------------------------------------

FOUR_PLACES = Decimal("0.0001")
ZERO_PLACES = Decimal("1")


def round_4dp(value: Decimal) -> Decimal:
    return value.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


def round_int_cents(value: Decimal) -> int:
    return int(value.quantize(ZERO_PLACES, rounding=ROUND_HALF_UP))


def dec(x) -> Decimal:
    """Safe Decimal coercion for int/str/float (floats go through str to avoid binary noise)."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        return Decimal(str(x))
    return Decimal(str(x))


def add_days(d: date, days: int) -> date:
    return d + timedelta(days=days)
