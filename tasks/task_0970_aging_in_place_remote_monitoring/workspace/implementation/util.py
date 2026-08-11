"""Time and numeric helpers. All temporal logic uses the logical clock."""
from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP


def iso(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-05-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    if not isinstance(s, str):
        return None
    try:
        t = s.strip()
        if t.endswith(("Z", "z")):
            t = t[:-1] + "+00:00"
        d = datetime.fromisoformat(t)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        return None


def parse_date(s):
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s.strip())
    except Exception:
        return None


def rhu_cents(x):
    """Round half up to integer cents."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round1d(x):
    """Round half up to one decimal place, returned as Decimal."""
    if not isinstance(x, Decimal):
        x = Decimal(str(x))
    return x.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
