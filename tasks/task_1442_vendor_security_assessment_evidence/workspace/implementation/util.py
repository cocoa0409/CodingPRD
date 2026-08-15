"""Time, id, and numeric helpers. All timestamps are ISO 8601 UTC with three
fractional digits. All deadline arithmetic is whole-day granular on top of the
logical clock. Scores use Decimal with ROUND_HALF_UP at exactly 2dp; per-item
products are never rounded before the final sum.
"""
import calendar
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db

ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def now():
    return db.clock_dt


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """Serialize an aware datetime as ISO 8601 UTC with 3 fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str) or not ISO_RE.match(value.strip()):
        raise ValueError("not an ISO 8601 datetime")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # normalize +0000 -> +00:00
    if re.search(r"[+-]\d{4}$", s):
        s = s[:-5] + s[-5:-2] + ":" + s[-2:]
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_dt(value):
    try:
        parse_dt(value)
        return True
    except (ValueError, TypeError):
        return False


def add_months(dt, months):
    """Add calendar months, clamping the day to the target month's length."""
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


def dec(x):
    """Exact Decimal from a JSON number (via str to avoid float dust)."""
    return Decimal(str(x))


def round2(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def num(d):
    """Serialize a Decimal score as a JSON number."""
    return float(d)


def days_between(later, earlier):
    """Whole days between two datetimes (floor semantics)."""
    return (later - earlier).days
