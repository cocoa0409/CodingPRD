"""The logical site clock (PRD section 2.5) plus timestamp helpers.

Every timestamp the server stamps, every rain-blackout comparison, every BMP
currency check, every outage-window containment test and every delay-day count
reads from this single logical UTC clock rather than from wall-clock time.
Until it has been set explicitly the clock reads 2026-08-01T00:00:00Z.
"""

import re
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = DEFAULT_NOW


def now():
    return _now


def set_now(instant):
    global _now
    _now = instant
    return _now


def reset():
    global _now
    _now = DEFAULT_NOW


_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_datetime(raw):
    """Parse an ISO-8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(raw, str):
        return None
    m = _DT_RE.match(raw.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tzs = m.group(8)
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if tzs in (None, "Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if tzs[0] == "+" else -1
    body = tzs[1:].replace(":", "")
    offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return (naive - sign * offset).replace(tzinfo=timezone.utc)


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(raw):
    if not isinstance(raw, str):
        return None
    m = _DATE_RE.match(raw.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fmt_datetime(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def rhu(value, places):
    """Round half up to `places` decimals; returns a Decimal."""
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return d.quantize(exp, rounding=ROUND_HALF_UP)


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def money(value):
    """Round half up to whole cents, as an int."""
    return int(rhu(value, 0))


def num(value, places):
    """Round half up to `places` decimals, as a float."""
    return float(rhu(value, places))
