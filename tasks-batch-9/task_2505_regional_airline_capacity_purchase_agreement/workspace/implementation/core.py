"""Core primitives: logical clock, id minting, timestamp formatting, money helpers."""

import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

# PRD 2.5 - the logical clock begins at this fixed instant on every boot.
DEFAULT_CLOCK_INSTANT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class LogicalClock(object):
    def __init__(self):
        self.current = DEFAULT_CLOCK_INSTANT

    def reset(self):
        self.current = DEFAULT_CLOCK_INSTANT

    def set(self, dt):
        self.current = dt.astimezone(UTC)

    def now(self):
        return self.current

    def iso(self):
        return iso_ms(self.current)

    def date(self):
        return self.current.date()


clock = LogicalClock()


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits, Z suffix."""
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))


def new_id():
    return str(uuid.uuid4())


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def parse_iso_datetime(value):
    """Parse an ISO-8601 instant into an aware UTC datetime; None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    tz = m.group(8)
    try:
        if tz in (None, "Z", "z"):
            dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
        else:
            sign = 1 if tz[0] == "+" else -1
            body = tz[1:].replace(":", "")
            offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4])) * sign
            dt = datetime(year, month, day, hour, minute, second, micro,
                          tzinfo=timezone(offset))
    except ValueError:
        return None
    return dt.astimezone(UTC)


def parse_date(value):
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        tzinfo=UTC).date()
    except ValueError:
        return None


def is_month(value):
    if not isinstance(value, str):
        return False
    m = _MONTH_RE.match(value.strip())
    if not m:
        return False
    return 1 <= int(m.group(2)) <= 12


# --------------------------------------------------------------------------- money
CENT = Decimal("0.01")
MILLI = Decimal("0.001")
ZERO2 = Decimal("0.00")
ZERO3 = Decimal("0.000")


def dec(value):
    """Exact Decimal from int/float/str/Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round2(value):
    """PRD 2.6 - round half up to two decimal places."""
    return dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def round3(value):
    return dec(value).quantize(MILLI, rounding=ROUND_HALF_UP)


def floor_div(numerator, denominator):
    """Integer division flooring the quotient (truncation toward zero, PRD 2.6)."""
    if denominator == 0:
        return 0
    return int(dec(numerator) // dec(denominator))


def decimal_places(value):
    exponent = dec(value).normalize().as_tuple().exponent
    if exponent >= 0:
        return 0
    return -exponent
