"""Shared primitives: exact-decimal rounding, ISO-8601 datetime handling, ids."""

import random
import re
import string
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def real_now():
    return datetime.now(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_dt(real_now())


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_dt(value):
    """Parse an ISO-8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a bare ISO-8601 calendar date (YYYY-MM-DD).  Returns date or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def is_uuid(value):
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def dec(value):
    """Coerce an int/Decimal/str into Decimal.  Raises InvalidOperation on junk."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise InvalidOperation("bool is not numeric")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):  # only if a caller bypassed parse_float=Decimal
        return Decimal(repr(value))
    return Decimal(str(value))


def rhu(value, places):
    """Round half up on the EXACT decimal value (never a binary float)."""
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def dmin(a, b):
    return a if a <= b else b


def dmax(a, b):
    return a if a >= b else b


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def whole_minutes(start, end):
    """Duration in whole minutes, or None when it is not an integral minute count."""
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return None
    if abs(seconds % 60) > 1e-9:
        return None
    return int(round(seconds / 60.0))


def out_num(value):
    """JSON projection for a numeric field."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    return float(value)


def half_open_overlap(a_start, a_end, b_start, b_end):
    """[a_start, a_end) intersects [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


def closed_overlap(a_start, a_end, b_start, b_end):
    """[a_start, a_end] intersects [b_start, b_end] -- touching endpoints conflict."""
    return a_start <= b_end and b_start <= a_end
