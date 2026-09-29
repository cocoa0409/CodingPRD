"""Time, id, and numeric helpers."""
import calendar
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, ROUND_CEILING

UTC = timezone.utc


# ---------------------------------------------------------------- identifiers
def new_uuid():
    return str(uuid.uuid4())


_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


# ------------------------------------------------------------------ timestamps
def fmt_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO 8601 instant.  Raises ValueError when unparseable."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not a datetime string")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        raise ValueError("unparseable datetime: %r" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def real_now():
    return datetime.now(UTC)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def add_months(dt, months):
    """Calendar month arithmetic: preserve time of day, clamp to last day."""
    total = (dt.year * 12 + (dt.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


# ------------------------------------------------------------------- rounding
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up_int(value):
    """Round to a whole number (cents) half up."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up(value, places):
    exp = Decimal(1).scaleb(-places)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


def floor_int(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_DOWN))


def ceil_int(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_CEILING))


def decimal_places(value):
    d = dec(value)
    exp = d.as_tuple().exponent
    if not isinstance(exp, int):
        return 0
    return max(0, -exp)


# ------------------------------------------------------------ month intervals
def parse_year_month(value):
    """'YYYY-MM' -> (year, month).  Raises ValueError when malformed."""
    if not isinstance(value, str):
        raise ValueError("not a month string")
    text = value.strip()
    if len(text) != 7 or text[4] != "-":
        raise ValueError("bad month format")
    y, m = text[:4], text[5:]
    if not (y.isdigit() and m.isdigit()):
        raise ValueError("bad month format")
    year, month = int(y), int(m)
    if not (1 <= month <= 12):
        raise ValueError("bad month value")
    return year, month


def month_index(value):
    year, month = parse_year_month(value)
    return year * 12 + (month - 1)
