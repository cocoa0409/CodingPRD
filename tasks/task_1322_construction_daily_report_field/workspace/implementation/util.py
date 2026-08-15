import re
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(v):
    if not isinstance(v, str):
        return None
    s = v.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(v):
    if not isinstance(v, str) or not ISO_DATE_RE.match(v):
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def to_dec(v):
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def q2(v):
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q3(v):
    return v.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def q0(v):
    return v.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def out_num(v):
    """Decimal -> JSON-safe number (int when integral, else float)."""
    if isinstance(v, Decimal):
        if v == v.to_integral_value():
            return int(v)
        return float(v)
    return v
