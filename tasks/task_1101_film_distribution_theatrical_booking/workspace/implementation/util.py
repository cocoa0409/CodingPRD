"""Time, ids, decimal helpers."""
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP


DEFAULT_LOGICAL_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


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


def dec_pct(value):
    """Coerce to Decimal at 4 places, ROUND_HALF_UP."""
    if value is None:
        return None
    d = Decimal(str(value))
    return d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def dec_str(d):
    """Format a Decimal percentage at exactly 4 decimals as float for JSON output."""
    if d is None:
        return None
    if not isinstance(d, Decimal):
        d = Decimal(str(d))
    q = d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


def round_half_up_int(d):
    """Round Decimal to integer cents, half-up."""
    if not isinstance(d, Decimal):
        d = Decimal(str(d))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
