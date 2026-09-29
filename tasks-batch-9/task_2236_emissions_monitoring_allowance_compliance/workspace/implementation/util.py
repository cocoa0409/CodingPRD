"""Low level helpers: ids, logical-clock friendly timestamp handling, and
round-half-up decimal arithmetic.

Every numeric result the API stores is produced through :func:`rhu`, which
quantizes with ``decimal.ROUND_HALF_UP`` (PRD 2.6 -- "half away from zero").
Python's built-in ``round()`` is never used.
"""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

UTC = timezone.utc

_ALNUM = string.ascii_uppercase + string.digits


def new_id():
    """Entity ids are bare UUIDs -- no prefix (PRD 2.5)."""
    return str(uuid.uuid4())


def new_request_id():
    """``req_`` + 20 random alphanumeric characters (PRD 2.2)."""
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def D(value):
    """Coerce to ``Decimal`` through ``str`` so float artefacts never leak in."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    return Decimal(str(value))


def rhu(value, places):
    """Round *value* half-up to *places* decimals and return a float."""
    quant = Decimal(1).scaleb(-places)
    return float(D(value).quantize(quant, rounding=ROUND_HALF_UP))


def rhu_dec(value, places):
    """Same as :func:`rhu` but keeps the ``Decimal``."""
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def ceil_int(value):
    """Integer ceiling (PRD 2.6: obligation/penalty tonnage ceils, never rounds)."""
    d = D(value)
    truncated = int(d)
    if d > truncated:
        truncated += 1
    return truncated


def sample_stdev(values):
    """Sample standard deviation (n-1 denominator) as an exact ``Decimal``."""
    n = len(values)
    if n < 2:
        return Decimal(0)
    total = sum((D(v) for v in values), Decimal(0))
    mean = total / D(n)
    acc = Decimal(0)
    for v in values:
        diff = D(v) - mean
        acc += diff * diff
    variance = acc / D(n - 1)
    if variance <= 0:
        return Decimal(0)
    return variance.sqrt()


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a ``Z`` suffix."""
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO 8601 timestamp; return ``None`` when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def truncate_to_hour(dt):
    return dt.replace(minute=0, second=0, microsecond=0)


def is_on_the_hour(dt):
    return dt.minute == 0 and dt.second == 0 and dt.microsecond == 0


def quarter_of(dt):
    return (dt.month - 1) // 3 + 1


def hours_before(dt, hours):
    return dt - timedelta(hours=hours)


def is_number(value):
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def to_decimal_or_none(value):
    try:
        return D(value)
    except (InvalidOperation, ValueError, TypeError):
        return None
