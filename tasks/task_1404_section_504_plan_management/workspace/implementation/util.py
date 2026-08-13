"""Time helpers, precision math, and record serialization."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError, ERR_INVALID_REQUEST


def iso(d):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if d is None:
        return None
    d = d.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def parse_dt(value, field):
    """Parse an ISO 8601 input (date or datetime, 'Z' or offset) to an aware UTC datetime."""
    if not isinstance(value, str) or not value.strip():
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1],
                       f"Field '{field}' must be an ISO 8601 string")
    t = value.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1],
                       f"Field '{field}' is not a valid ISO 8601 timestamp")
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def days_between(later, earlier):
    """Whole calendar days: floor of the difference expressed in days."""
    return int((later - earlier).total_seconds() // 86400)


def add_calendar_years(d, years):
    """Calendar-year offset ('exactly two years after trained_at'): Feb 29 -> Feb 28."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(month=2, day=28, year=d.year + years)


def pct2(numerator, denominator):
    """Percentage rounded half-up to exactly 2 decimals; empty window -> 100.0 (ratio 1.0)."""
    if denominator == 0:
        return 100.0
    v = (Decimal(numerator) * Decimal(100)) / Decimal(denominator)
    return float(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def dump(rec):
    """Serialize a stored record: drop internals, format datetimes."""
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = iso(v)
        else:
            out[k] = v
    return out
