"""Time parsing/formatting and rounding helpers."""
import re
import math
import datetime
from decimal import Decimal, ROUND_HALF_UP

UTC = datetime.timezone.utc

_ISO_RE = re.compile(
    r'^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(\.\d+)?'
    r'(Z|[+-]\d{2}:?\d{2})?$'
)


def parse_iso(s):
    """Parse an ISO-8601 instant into a timezone-aware UTC datetime.

    Accepts a trailing ``Z``, an explicit offset, or no zone (assumed UTC),
    and fractional seconds of arbitrary length.
    """
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    t = s.strip()
    m = _ISO_RE.match(t)
    if not m:
        raise ValueError("malformed timestamp: %r" % s)
    year, month, day, hh, mm, ss = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        digits = frac[1:]
        digits = (digits + "000000")[:6]
        micro = int(digits)
    zone = m.group(8)
    if zone in (None, "Z", "z"):
        tz = UTC
    else:
        z = zone.replace(":", "")
        sign = 1 if z[0] == "+" else -1
        oh = int(z[1:3])
        om = int(z[3:5])
        tz = datetime.timezone(sign * datetime.timedelta(hours=oh, minutes=om))
    dt = datetime.datetime(year, month, day, hh, mm, ss, micro, tz)
    return dt.astimezone(UTC)


def format_iso(dt):
    """Format a datetime as ISO-8601 UTC with three fractional digits and Z."""
    dt = dt.astimezone(UTC)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % ms)


def now_utc():
    return datetime.datetime.now(UTC)


def floor_days(later, earlier):
    """Whole elapsed days from ``earlier`` to ``later`` (partial day discarded)."""
    seconds = (later - earlier).total_seconds()
    return int(math.floor(seconds / 86400.0))


def add_days(dt, days):
    return dt + datetime.timedelta(days=days)


def round_half_up(value):
    """Round a Decimal/number half-up to an integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    """Round a Decimal/number half-up to two decimal places, returning a float."""
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
