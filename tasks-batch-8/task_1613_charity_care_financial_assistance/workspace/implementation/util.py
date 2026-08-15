"""Shared helpers: ids, timestamps, logical clock, decimal rounding."""
import random
import string
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def now_ts() -> str:
    """Wall-clock ISO 8601 UTC timestamp with three fractional digits.

    Used for created_at / updated_at / api_request_timestamp (PRD 2.2, 2.5).
    Business 'now' timestamps use the logical clock below (PRD 2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4): starts at exactly 2026-08-01T00:00:00Z; never wall-clock.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def parse_dt(s: str) -> datetime:
    """Parse an ISO 8601 timestamp; normalize to UTC at second precision."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def fmt_dt(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def is_valid_datetime(s) -> bool:
    if not isinstance(s, str):
        return False
    try:
        parse_dt(s)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def is_valid_date(s) -> bool:
    if not isinstance(s, str):
        return False
    try:
        date.fromisoformat(s.strip())
        return True
    except (ValueError, TypeError, AttributeError):
        return False


class LogicalClock:
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


# ---------------------------------------------------------------------------
# Decimal helpers (PRD 2.6): round-half-up only, applied exactly once.
# ---------------------------------------------------------------------------

def to_decimal(v) -> Decimal:
    """Exact Decimal from an int/float/Decimal JSON number."""
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise TypeError("bool is not a number here")
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, float):
        return Decimal(str(v))
    raise TypeError(f"not numeric: {v!r}")


def round_half_up(x: Decimal, places: int) -> Decimal:
    quantum = Decimal(1).scaleb(-places)  # 10^-places
    return x.quantize(quantum, rounding=ROUND_HALF_UP)


def dec_to_float(x: Decimal) -> float:
    return float(x)
