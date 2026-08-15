"""Shared helpers: ids, timestamps, logical clock, money/decimal rounding."""
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
    """ISO 8601 UTC timestamp with three fractional digits (envelope meta)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def parse_dt(s: str) -> datetime:
    """Parse an ISO 8601 datetime into an aware UTC datetime (microsecond-free)."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0)


def fmt_dt(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class LogicalClock:
    """Server-side logical clock. Startup default 2026-08-01T00:00:00Z; the
    clock is free-running (PRD pins no monotonicity rule for set calls)."""

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
# Money / decimal helpers (PRD 2.6)
# ---------------------------------------------------------------------------

_CENT = Decimal("1")


def rhu_cents(value: Decimal) -> int:
    """Round a Decimal to integer cents, ROUND_HALF_UP."""
    return int(value.quantize(_CENT, rounding=ROUND_HALF_UP))


def duty_amount(quantity: int, unit_value_cents: int, duty_rate: Decimal) -> int:
    """round_half_up(quantity x unit_value_cents x duty_rate) in integer cents."""
    v = Decimal(int(quantity)) * Decimal(int(unit_value_cents)) * duty_rate
    return rhu_cents(v)
