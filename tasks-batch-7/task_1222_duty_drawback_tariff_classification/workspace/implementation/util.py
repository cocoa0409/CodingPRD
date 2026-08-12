"""Time, rounding, and identifier helpers.

Money is integer cents; rates are integer basis points. Every rounding is
round-half-up to integer cents, applied exactly where each calculation pins it.
Exact rationals (Fraction) are used so no floating-point error ever creeps in.
"""
import math
import uuid
from datetime import datetime, timezone
from fractions import Fraction


def new_id():
    return str(uuid.uuid4())


def wall_now_iso():
    """Wall-clock UTC timestamp with three fractional digits (created_at etc.)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("expected an ISO 8601 string")
    text = value.strip()
    if not text:
        raise ValueError("empty datetime")
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"invalid datetime: {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Canonical UTC rendering: seconds precision, fractional only when set."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def add_years(dt, years):
    """Whole-year addition (statutory windows); Feb 29 clamps to Feb 28."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        return dt.replace(year=dt.year + years, month=2, day=28)


def rhu(fr):
    """Round-half-up of a non-negative Fraction to an integer."""
    return math.floor(fr + Fraction(1, 2))
