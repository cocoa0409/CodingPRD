"""Time, decimal-money and misc primitives."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def parse_dt(value):
    """Parse an ISO-8601 string to an aware UTC datetime; None if invalid."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD section 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def dec(v):
    return Decimal(str(v))


def round_cents(d):
    """Round a Decimal half-up to whole cents -> int."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money_mul(quantity, rate_cents):
    """round_half_up(quantity * rate_cents) as integer cents."""
    return round_cents(dec(quantity) * dec(rate_cents))


def round_score(d):
    """Round a Decimal half-up to two decimal places -> float."""
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))
