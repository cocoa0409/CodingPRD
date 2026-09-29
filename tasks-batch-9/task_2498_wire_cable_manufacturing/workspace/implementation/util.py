"""Numeric, date and serialization helpers.

Monetary and other precision-sensitive values are carried as ``Decimal``
throughout and only converted to JSON numbers at the response boundary
(PRD 2.5: never floating point arithmetic for money).
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


def D(x):
    """Coerce to Decimal without inheriting binary float artifacts."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        raise ValueError("bool is not a number")
    return Decimal(str(x))


def rhu(x, places):
    """Round half up to ``places`` decimal places (PRD 2.5)."""
    q = Decimal(1).scaleb(-places)
    return D(x).quantize(q, rounding=ROUND_HALF_UP)


def money(x):
    return rhu(x, 2)


def iso_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso_dt(s):
    """Parse an ISO 8601 datetime into a naive UTC datetime, or None."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_ymd(s):
    """Parse a strict YYYY-MM-DD date string, or None."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if len(t) != 10 or t[4] != "-" or t[7] != "-":
        return None
    try:
        return date(int(t[0:4]), int(t[5:7]), int(t[8:10]))
    except ValueError:
        return None


def ymd(d):
    return d.isoformat()


def add_days(d, n):
    """Advance a date (or YYYY-MM-DD string) by n whole calendar days."""
    if isinstance(d, str):
        d = parse_ymd(d)
    return d + timedelta(days=int(n))


def day_diff(later, earlier):
    """Whole calendar days between two dates (or YYYY-MM-DD strings)."""
    if isinstance(later, str):
        later = parse_ymd(later)
    if isinstance(earlier, str):
        earlier = parse_ymd(earlier)
    return (later - earlier).days


def jsonable(obj):
    """Recursively convert Decimals to JSON numbers and drop private keys."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return obj
