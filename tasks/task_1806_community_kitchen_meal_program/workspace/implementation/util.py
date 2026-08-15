"""Shared helpers: ids, timestamps, logical clock, rounding."""
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
    """ISO 8601 UTC timestamp with three fractional digits (wall clock, for meta)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def _parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("datetime must be a string")
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

    def set(self, to_iso8601: str) -> datetime:
        self._dt = _parse_dt(to_iso8601)
        return self._dt


CLOCK = LogicalClock()


def parse_datetime(s: str) -> datetime:
    return _parse_dt(s)


def parse_date(s: str) -> date:
    return date.fromisoformat(s.strip())


def fmt_datetime(dt: datetime) -> str:
    return _fmt_dt(dt)


# ---------------------------------------------------------------------------
# Precision helpers (PRD 2.10)
# ---------------------------------------------------------------------------

def round_half_up_2dp(value) -> float:
    """Round a numeric to 2 decimal places, ROUND_HALF_UP. Returns a float
    that serializes cleanly (e.g. 100.01)."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def round_half_up_4dp(value) -> float:
    d = Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(d)


def ceil_int(value) -> int:
    d = Decimal(str(value))
    i = d.to_integral_value(rounding="ROUND_CEILING")
    return int(i)


def hours_between(start: datetime, end: datetime) -> float:
    """Fractional hours between two instants, rounded half up to 2dp."""
    secs = (end - start).total_seconds()
    return round_half_up_2dp(Decimal(str(secs)) / Decimal("3600"))
