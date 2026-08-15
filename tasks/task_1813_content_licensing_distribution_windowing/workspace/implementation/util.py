"""Shared helpers: ids, timestamps, logical clock, money rounding.

All time-dependent behavior keys off the logical clock, never wall-clock time.
The logical clock starts at exactly 2026-08-01T00:00:00Z at server startup.
Logical-clock timestamps serialize at second precision ("...Z"); the envelope's
api_request_timestamp is wall-clock with three fractional digits.
"""
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
    """Wall-clock ISO 8601 UTC timestamp with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def parse_dt(s):
    """Parse an ISO 8601 datetime string; normalize to UTC, second precision."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0)


def fmt_dt(dt) -> str:
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


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


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


# ---------------------------------------------------------------------------
# Money / rounding
# ---------------------------------------------------------------------------

def round_half_up_int(numer, denom) -> int:
    """round_half_up(numer / denom) to an integer using exact integer math."""
    numer = int(numer)
    denom = int(denom)
    if denom == 0:
        raise ZeroDivisionError("denom")
    if numer >= 0:
        return (2 * numer + denom) // (2 * denom)
    return -((2 * (-numer) + denom) // (2 * denom))


def apply_pct_round(amount_cents: int, pct) -> int:
    """round_half_up(amount_cents * pct / 100) to integer cents (pct may be float)."""
    d = (Decimal(int(amount_cents)) * Decimal(str(pct)) / Decimal(100)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(d)


def norm_num(v):
    """Serialize integral floats as ints for clean JSON output."""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v
