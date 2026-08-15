"""Shared helpers: ids, timestamps, logical clock, decimal math."""
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
    """ISO 8601 UTC timestamp with three fractional digits (wall clock, for
    created_at/updated_at resource metadata)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5): default 2026-08-01T00:00:00Z, never wall-clock.
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
        from errors import raise_error, ERR_INVALID_REQUEST
        new_dt = _parse_dt(to_iso8601)
        if new_dt < self._dt:
            raise_error(ERR_INVALID_REQUEST,
                        "clock regression: to_iso8601 is before the current logical time")
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
# Decimal math (PRD 2.7): money rounded half-up to 2 dp per component;
# quantities exact.
# ---------------------------------------------------------------------------

def dec(v) -> Decimal:
    """Exact Decimal from an int/float/str without binary float noise."""
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise TypeError("bool is not numeric")
    return Decimal(str(v))


def round_money(v) -> Decimal:
    return dec(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def num(v):
    """Emit a Decimal/exact value as a plain JSON number: int when integral."""
    d = dec(v)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def floor_decimal(v) -> int:
    d = dec(v)
    return int(d.to_integral_value(rounding="ROUND_FLOOR"))
