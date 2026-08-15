"""Shared helpers: ids, logical clock, datetime parse/format, decimal rounding."""
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

# PRD 2.4: startup default is exactly 2026-08-01T00:00:00Z, no wall-clock fallback.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def parse_dt(s) -> datetime:
    """Parse an ISO 8601 datetime; naive values are read as UTC; result is UTC."""
    if not isinstance(s, str):
        raise ValueError("datetime must be a string")
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt: datetime) -> str:
    """ISO 8601 UTC timestamp with three fractional digits (PRD 2.2/2.5)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


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

    def set_dt(self, dt: datetime) -> datetime:
        self._dt = dt.astimezone(timezone.utc)
        return self._dt


CLOCK = LogicalClock()


def dec(value) -> Decimal:
    """Exact decimal from an int/float/str JSON number."""
    return Decimal(str(value))


def round_half_up(x: Decimal, places: int) -> Decimal:
    return x.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def round_half_up_int(x: Decimal) -> int:
    """Round half-up to whole cents (PRD 2.6: no fractional cent persists)."""
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
