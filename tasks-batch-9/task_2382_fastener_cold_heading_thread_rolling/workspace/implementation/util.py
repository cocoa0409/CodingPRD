"""Clock, rounding and datetime helpers.

Every timestamp the server writes comes from the logical clock held in db.py;
the wall clock is never consulted (PRD 2.4).
"""

import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, getcontext

getcontext().prec = 60

UTC = timezone.utc

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """Render a datetime as ISO-8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO-8601 datetime.  Returns None when the value is unparseable."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    off = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    except ValueError:
        return None
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        off = off[1:].replace(":", "")
        delta = timedelta(hours=int(off[:2]), minutes=int(off[2:4]))
        base = base - sign * delta
    return base


def dt_of(record, field):
    """Parse a stored ISO string field of a record into a datetime."""
    return parse_dt(record.get(field))


# --------------------------------------------------------------------------
# numeric helpers
# --------------------------------------------------------------------------

def dec(value):
    """Coerce int / float / str / Decimal into Decimal without float noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("bool is not numeric")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to `places` decimal places, returning a Decimal."""
    q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    """Round half up to the nearest integer."""
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def dsqrt(value):
    """Exact-enough Decimal square root."""
    return dec(value).sqrt()


def ceil_sqrt(n):
    """ceil(sqrt(n)) for a non-negative integer, computed exactly."""
    n = int(n)
    if n <= 0:
        return 0
    root = math.isqrt(n)
    return root if root * root == n else root + 1
