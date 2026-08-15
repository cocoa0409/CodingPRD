"""Shared helpers: ids, timestamps, logical clock, decimal rounding (PRD 2.5/2.7)."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def now_ts() -> str:
    """ISO 8601 UTC with three fractional digits (wall clock; used for meta timestamps)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s: str) -> datetime:
    """Parse an ISO 8601 datetime into an aware UTC datetime at second precision."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def is_valid_dt(s) -> bool:
    try:
        parse_dt(s)
        return True
    except (ValueError, TypeError):
        return False


def fmt_dt(dt: datetime) -> str:
    """Second-precision ISO 8601 UTC (logical-clock timestamps, window echoes)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_dt_ms(dt: datetime) -> str:
    """Three-fractional-digit ISO 8601 UTC (created_at / updated_at per PRD 2.4)."""
    base = dt.astimezone(timezone.utc)
    return base.strftime("%Y-%m-%dT%H:%M:%S.") + f"{base.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5): default 2026-08-01T00:00:00Z, never wall-clock.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self._dt = parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return fmt_dt(self._dt)

    def set(self, to_iso8601: str) -> datetime:
        new_dt = parse_dt(to_iso8601)
        if new_dt < self._dt:
            from errors import raise_error, ERR_INVALID_REQUEST
            raise_error(ERR_INVALID_REQUEST,
                        "clock regression: to_iso8601 is before the current logical time")
        self._dt = new_dt
        return self._dt


CLOCK = LogicalClock()

# Monotonic insertion sequence used as a deterministic tie-breaker wherever
# created_at ordering ties (FEFO lots, preemption candidates, list sort).
_seq_counter = [0]


def next_seq() -> int:
    _seq_counter[0] += 1
    return _seq_counter[0]


# ---------------------------------------------------------------------------
# Decimal arithmetic (PRD 2.7: round half up at the point the rule specifies)
# ---------------------------------------------------------------------------

def dec(v) -> Decimal:
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def rhu_int(value) -> int:
    """round_half_up(value) to an integer."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_dec(value, dp: int) -> Decimal:
    """round_half_up(value) to dp decimal places, returned as Decimal."""
    q = Decimal(1).scaleb(-dp)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_float(value, dp: int) -> float:
    """round_half_up(value) to dp decimal places, returned as float for JSON."""
    return float(rhu_dec(value, dp))


def ceil_div_int(numer: int, denom: int) -> int:
    numer = int(numer)
    denom = int(denom)
    return -(-numer // denom)
