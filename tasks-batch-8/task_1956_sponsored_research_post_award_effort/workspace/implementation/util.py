"""Time, decimal, and rounding helpers (PRD section 2.4/2.5)."""
from calendar import monthrange
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("1")
TWO_DP = Decimal("0.01")


def D(x):
    """Coerce a JSON number to Decimal exactly (via str for floats)."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        raise ValueError("bool is not numeric")
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        return Decimal(str(x))
    if isinstance(x, str):
        return Decimal(x)
    raise ValueError("not numeric")


def rhu(d):
    """Round half-up (ties away from zero) to integer cents."""
    return int(d.quantize(CENT, rounding=ROUND_HALF_UP))


def rhu2(d):
    """Round half-up to two decimal places, returned as Decimal."""
    return d.quantize(TWO_DP, rounding=ROUND_HALF_UP)


def f2(d):
    """Decimal -> float for JSON serialization of 2dp percentages."""
    return float(d)


def parse_dt(s):
    """Parse an ISO-8601 datetime (Z or offset); date-only allowed. Returns aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if not t:
        raise ValueError("empty")
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Serialize aware UTC datetime; seconds precision, or 3 fractional digits when sub-second."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso():
    """Wall-clock timestamp with three fractional digits (created_at/updated_at/meta)."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def whole_days(a, b):
    """Integer whole days between two instants (floor; timedelta.days semantics)."""
    return (b - a).days


def add_months(dt, months):
    """Add calendar months; day clamped to month end (NCE arithmetic, PRD 3.8)."""
    m = dt.year * 12 + (dt.month - 1) + months
    y, mo = divmod(m, 12)
    mo += 1
    d = min(dt.day, monthrange(y, mo)[1])
    return dt.replace(year=y, month=mo, day=d)


def add_days(dt, days):
    return dt + timedelta(days=days)
