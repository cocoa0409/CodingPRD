"""Shared helpers: ids, timestamps, logical clock, date arithmetic, rounding."""
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
    """ISO 8601 UTC timestamp with three fractional digits (wall clock).

    Used for created_at / updated_at / api_request_timestamp — system bookkeeping
    fields. Business logic (CIAC expiry, reversal dating, closed_at) uses the
    logical CLOCK instead.
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.6): single time authority for CIAC pledge expiry,
# reversal charge dating, and period closed_at. Never falls back to wall clock.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def parse_dt(s) -> datetime:
    """Parse an ISO 8601 datetime; naive values are treated as UTC."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class LogicalClock:
    def __init__(self):
        self._dt = parse_dt(DEFAULT_CLOCK).replace(microsecond=0)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return fmt_dt(self._dt)

    def today(self) -> date:
        return self._dt.date()

    def set(self, to_iso8601: str) -> datetime:
        self._dt = parse_dt(to_iso8601).replace(microsecond=0)
        return self._dt


CLOCK = LogicalClock()


def parse_date(s) -> date:
    if not isinstance(s, str):
        raise ValueError("not a string")
    return date.fromisoformat(s.strip())


# ---------------------------------------------------------------------------
# Rounding discipline (PRD 2.5): round half up to whole cents, per row.
# ---------------------------------------------------------------------------

def rhu_dec(value: Decimal) -> int:
    """Round a Decimal to the nearest integer, half up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_div(numer: int, denom: int) -> int:
    """round_half_up(numer / denom) with exact integer arithmetic."""
    numer = int(numer)
    denom = int(denom)
    if denom <= 0:
        raise ZeroDivisionError("rhu_div denominator must be positive")
    if numer >= 0:
        return (2 * numer + denom) // (2 * denom)
    return -((2 * (-numer) + denom) // (2 * denom))


def dec(x) -> Decimal:
    """Exact Decimal from an int/float/str JSON number."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        raise ValueError("bool is not a number")
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        return Decimal(str(x))
    if isinstance(x, str):
        return Decimal(x)
    raise ValueError(f"not a number: {x!r}")


def num_out(d: Decimal):
    """Serialize a computed rate Decimal as a JSON number (int when integral)."""
    if d == d.to_integral_value():
        return int(d)
    return float(d)
