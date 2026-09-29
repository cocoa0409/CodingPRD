"""Shared primitives: logical clock, ids, timestamp formatting, decimal helpers."""
import itertools
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

# ---------------------------------------------------------------- logical clock
# PRD 2.6: at process start the clock reads 2026-08-01T00:00:00Z.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_DEFAULT}


def now():
    return _clock["now"]


def set_now(dt):
    _clock["now"] = dt.astimezone(timezone.utc)


def days(n):
    return timedelta(days=n)


# ----------------------------------------------------------------- timestamps
def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_ts(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ------------------------------------------------------------------ identity
def new_id():
    """UUID with no type prefix of any kind (PRD 2.4)."""
    return str(uuid.uuid4())


_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


_counter = itertools.count(1)


def next_seq():
    """Monotonic insertion counter, used as the stable tie-break for created_at."""
    return next(_counter)


# ------------------------------------------------------------------- decimals
ZERO = Decimal("0")
ONE = Decimal("1")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to `places` decimal places, exact decimal arithmetic."""
    q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def ceil_cents(value):
    """Round up to the next whole unit regardless of remainder."""
    return dec(value).to_integral_value(rounding=ROUND_CEILING)


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def q2(value):
    return rhu(value, 2)


def num(value):
    """Serialize a decimal quantity as a JSON number."""
    if value is None:
        return None
    return float(dec(value))


def decimal_places(value):
    exponent = dec(value).normalize().as_tuple().exponent
    return -exponent if exponent < 0 else 0
