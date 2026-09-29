"""Exact-decimal arithmetic, RFC 3339 parsing and small helpers."""

import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, getcontext

getcontext().prec = 60

ZERO = Decimal("0")
ONE = Decimal("1")

_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_ALNUM = string.ascii_uppercase + string.digits


# ---------------------------------------------------------------------------
# rounding
# ---------------------------------------------------------------------------
def dec(value):
    """Coerce an int/Decimal/str to Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def _exp(places):
    if places <= 0:
        return Decimal(1)
    return Decimal(1).scaleb(-places)


def q(value, places):
    """Round half up to `places` decimals, returning a Decimal at that scale."""
    return dec(value).quantize(_exp(places), rounding=ROUND_HALF_UP)


def q0(value):
    """Round half up to a whole unit, returning an int (money / days)."""
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def q1(value):
    return q(value, 1)


def q2(value):
    return q(value, 2)


def q4(value):
    return q(value, 4)


def ifloor(value):
    """Round down to a whole unit, returning an int."""
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_FLOOR))


def iceil(value):
    """Round up to a whole unit, returning an int."""
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_CEILING))


def geomean1(values):
    """Geometric mean of positive integers, rounded half up to one decimal."""
    n = len(values)
    if n == 0:
        return None
    product = Decimal(1)
    for v in values:
        product *= dec(v)
    if n == 1:
        root = product
    else:
        root = (product.ln() / Decimal(n)).exp()
    return q(root, 1)


# ---------------------------------------------------------------------------
# instants and dates
# ---------------------------------------------------------------------------
def parse_instant(raw):
    """Parse an RFC 3339 UTC instant ending in Z. Returns None when malformed."""
    if not isinstance(raw, str) or not _INSTANT_RE.match(raw):
        return None
    body = raw[:-1]
    try:
        if "." in body:
            head, frac = body.split(".", 1)
            frac = (frac + "000000")[:6]
            parsed = datetime.strptime(head, "%Y-%m-%dT%H:%M:%S").replace(
                microsecond=int(frac)
            )
        else:
            parsed = datetime.strptime(body, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def parse_date(raw):
    """Parse a YYYY-MM-DD calendar date. Returns None when malformed."""
    if not isinstance(raw, str) or not _DATE_RE.match(raw):
        return None
    try:
        return date(int(raw[0:4]), int(raw[5:7]), int(raw[8:10]))
    except ValueError:
        return None


def hours_between(start, end):
    """Elapsed hours from `start` to `end`, half up to two decimals (signed)."""
    seconds = dec((end - start).total_seconds())
    return q(seconds / Decimal(3600), 2)


def add_days(value, days):
    return value + timedelta(days=int(days))


def timedelta_hours(hours):
    return timedelta(hours=int(hours))


def date_str(value):
    if value is None:
        return None
    return value.strftime("%Y-%m-%d")


def compact_date(value):
    return value.strftime("%Y%m%d")


def instant_str(value):
    """Render an aware datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        "%03d" % (value.microsecond // 1000)
    ) + "Z"


def now_instant():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------
def new_uuid():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))
