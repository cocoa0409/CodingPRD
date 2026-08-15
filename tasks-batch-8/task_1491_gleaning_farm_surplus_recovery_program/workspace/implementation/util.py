from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR


def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime; None if invalid."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s[-1] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def dec1(x):
    """Round a numeric to 1 decimal place, round-half-up (weights)."""
    return Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def dec4(x):
    """Round a numeric to 4 decimal places, round-half-up (salvage ratio)."""
    return Decimal(str(x)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def iso_week_key(dt):
    iso = dt.isocalendar()
    return (iso[0], iso[1])


def intervals_overlap(s1, e1, s2, e2):
    """Half-open [s, e) overlap; adjacency (end == start) is permitted."""
    return s1 < e2 and s2 < e1


def floor_int(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_FLOOR))


def serialize(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out
