"""Rounding, datetime and identifier helpers.

PRD section 2.6: every rounding in this system is round-half-up.
PRD section 2.4: timestamps are ISO 8601 UTC with exactly three fractional digits.
"""

import decimal
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

decimal.getcontext().prec = 60

UTC = timezone.utc
CENT = Decimal("0.01")

_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?)?$"
)


def round_half_up(value, places=2):
    """Round a Decimal/number half away from zero to `places` decimals."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return d.quantize(exp, rounding=ROUND_HALF_UP)


def money(value):
    return round_half_up(value, 2)


def bps(value):
    """Basis-point integers: untruncated ratio rounded half up to a whole number."""
    return int(round_half_up(value, 0))


def to_decimal(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def parse_datetime(raw):
    """Parse an ISO 8601 UTC datetime. Returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    m = _DT_RE.match(raw.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, offset = m.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        dt = datetime(
            int(year),
            int(month),
            int(day),
            int(hour or 0),
            int(minute or 0),
            int(second or 0),
            micro,
            tzinfo=UTC,
        )
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * delta
    return dt


def format_datetime(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_days(dt, days):
    return dt + timedelta(days=days)
