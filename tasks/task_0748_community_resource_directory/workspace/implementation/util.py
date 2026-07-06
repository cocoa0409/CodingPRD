"""Utility functions: UUIDs, timestamp formatting/parsing, half-up rounding."""
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal


def new_id() -> str:
    return str(uuid.uuid4())


def fmt_ts(dt: datetime) -> str:
    """ISO 8601 UTC with 3 fractional-second digits: YYYY-MM-DDTHH:MM:SS.sssZ"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def parse_ts(s: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp. Accepts 'Z' suffix or explicit offset."""
    if not isinstance(s, str):
        raise ValueError("timestamp must be string")
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def half_up_2(x: float) -> float:
    """Round half-up to 2 decimal places, returning a float."""
    q = Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


def half_up_int(x: float) -> int:
    """Round half-up to whole integer."""
    q = Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def floor_years_between(dob_str: str, today: datetime) -> int:
    """Full years between an ISO date (YYYY-MM-DD) and a UTC datetime, floored."""
    dob = datetime.strptime(dob_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    years = today.year - dob.year
    # subtract 1 if we haven't hit the birthday yet this year
    if (today.month, today.day) < (dob.month, dob.day):
        years -= 1
    return years
