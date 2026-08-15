"""Shared helpers: ids, timestamps, the program-wide logical clock, calendar
arithmetic, and Decimal-based rounding (PRD 2.4, 2.5, 2.10).

Entity timestamps (created_at / updated_at / signed_date / acknowledged_at ...)
are stamped from the LOGICAL clock, never the wall clock. The response
envelope's meta.api_request_timestamp is wall-clock ISO 8601 with three
fractional digits (PRD 2.2).
"""
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


def now_ts() -> str:
    """Wall-clock ISO 8601 UTC timestamp with three fractional digits (envelope meta)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5): default 2026-08-01T00:00:00Z, strictly forward.
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
        """Logical clock reading as YYYY-MM-DDTHH:MM:SSZ (entity timestamp format)."""
        return _fmt_dt(self._dt)

    def today(self) -> date:
        return self._dt.date()

    def set(self, to_iso8601: str) -> datetime:
        """Advance the clock. Must move strictly forward (PRD 2.5)."""
        from errors import raise_error, ERR_INVALID_REQUEST
        new_dt = _parse_dt(to_iso8601)
        if new_dt <= self._dt:
            raise_error(ERR_INVALID_REQUEST,
                        "to_iso8601 does not advance the logical clock (strictly forward only)")
        self._dt = new_dt
        return self._dt


CLOCK = LogicalClock()


def parse_datetime(s: str) -> datetime:
    return _parse_dt(s)


def parse_date(s: str) -> date:
    return date.fromisoformat(s.strip())


def fmt_datetime(dt: datetime) -> str:
    return _fmt_dt(dt)


def add_months(d: date, months: int) -> date:
    """Calendrical month addition: 2027-01-31 + 1 month = 2027-02-28."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def add_years(d: date, years: int) -> date:
    return add_months(d, years * 12)


# ---------------------------------------------------------------------------
# Decimal math (PRD 2.10): half-up rounding; never binary float arithmetic.
# ---------------------------------------------------------------------------

def dec(value) -> Decimal:
    """Exact Decimal from an int/float/str JSON number."""
    return Decimal(str(value))


def round_half_up(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def money2(value: Decimal) -> float:
    """2dp round-half-up rendered as a JSON number."""
    return float(round_half_up(value, 2))


def weight1(value: Decimal) -> float:
    """1dp round-half-up rendered as a JSON number."""
    return float(round_half_up(value, 1))


def ceil_div(numer: int, denom: int) -> int:
    return -(-int(numer) // int(denom))
