"""Shared helpers: ids, timestamps, the logical clock, Decimal math.

All domain timestamps are stamped from the logical clock (PRD 2.4), which
starts at exactly 2026-08-01T00:00:00Z and moves only via
POST /_clock/set_current_utc. The canonical persisted format is whole-second
UTC ("YYYY-MM-DDTHH:MM:SSZ"). meta.api_request_timestamp is wall-clock with
three fractional digits (PRD 2.2).
"""
import math
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


def request_ts() -> str:
    """meta.api_request_timestamp: wall clock, ISO 8601 UTC, 3 fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def parse_dt(value):
    """Parse an ISO 8601 string to an aware UTC datetime. Raises ValueError."""
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def canon(dt: datetime) -> str:
    """Canonical persisted timestamp: whole-second UTC."""
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


class LogicalClock:
    def __init__(self):
        self._dt = parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return canon(self._dt)

    def set(self, to_iso8601: str) -> None:
        new_dt = parse_dt(to_iso8601)
        if new_dt < self._dt:
            from errors import raise_error, ERR_INVALID_REQUEST
            raise_error(ERR_INVALID_REQUEST,
                        "to_iso8601 is before the current logical clock")
        self._dt = new_dt


CLOCK = LogicalClock()


def add_days(ts_iso: str, days: int) -> str:
    return canon(parse_dt(ts_iso) + timedelta(days=days))


def whole_days_between(start_iso: str, end_iso: str) -> int:
    """Whole-day floor of (end - start) in days (may be negative)."""
    delta = parse_dt(end_iso) - parse_dt(start_iso)
    return math.floor(delta.total_seconds() / 86400)


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------

def dec(value) -> Decimal:
    """Exact decimal from a JSON number (int/float/str-safe)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not a number")
    return Decimal(str(value))


def round_half_up(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def cents(value: Decimal) -> int:
    """Round half-up to whole cents -> int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num(value):
    """JSON-serialize a Decimal as int when integral, else float."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value
