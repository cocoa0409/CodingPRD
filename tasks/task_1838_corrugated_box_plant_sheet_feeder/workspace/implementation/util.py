"""Time, ids, decimal helpers."""
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP


DEFAULT_LOGICAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def new_id():
    return str(uuid.uuid4())


def utcnow_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def iso_from_dt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    """Parse ISO 8601 string (allow trailing Z) to aware datetime. Return None if invalid."""
    if not isinstance(s, str):
        return None
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


def parse_date(s):
    """Parse an ISO date string (YYYY-MM-DD) to date. Return None if invalid."""
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s)
    except (ValueError, AttributeError):
        return None


# Decimal rounding helpers
FOUR_PLACES = Decimal("0.0001")
TWO_PLACES = Decimal("0.01")


def D(v):
    """Coerce a JSON numeric to Decimal without float artifacts."""
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise TypeError("boolean is not numeric")
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    if isinstance(v, str):
        return Decimal(v)
    raise TypeError(f"not numeric: {v!r}")


def round4(v):
    d = D(v)
    return d.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


def round2(v):
    d = D(v)
    return d.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def d2f(d):
    """Decimal to JSON-friendly float at pinned precision."""
    if d is None:
        return None
    if not isinstance(d, Decimal):
        d = D(d)
    return float(d)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))
