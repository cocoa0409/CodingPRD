"""Shared helpers: ids, timestamps, logical clock, decimal arithmetic (PRD 2.5/2.6)."""
import itertools
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
    """ISO 8601 UTC timestamp with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Decimal helpers — all cwt at 2dp round-half-up; money integer cents
# ---------------------------------------------------------------------------

CENT2 = Decimal("0.01")
CENT0 = Decimal("1")


def D(v) -> Decimal:
    """Coerce an int/float/str numeric to Decimal exactly."""
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise TypeError("bool is not numeric")
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, str):
        return Decimal(v)
    raise TypeError(f"not numeric: {v!r}")


def q2(v: Decimal) -> Decimal:
    return D(v).quantize(CENT2, rounding=ROUND_HALF_UP)


def q0(v: Decimal) -> int:
    return int(D(v).quantize(CENT0, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Datetime helpers — second precision for clock/fumigation, minute for lines
# ---------------------------------------------------------------------------

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


def parse_dt(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def fmt_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(s: str) -> date:
    return date.fromisoformat(s.strip())


def add_hours(dt: datetime, hours: int) -> datetime:
    return dt + timedelta(hours=hours)


_seq_counter = itertools.count(1)


def next_seq() -> int:
    return next(_seq_counter)
