"""Time, rounding, and parsing utilities bound to the logical clock."""
import math
import re
import uuid
from datetime import datetime, timedelta, date, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import store

_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def now_dt():
    """Current logical-clock instant as an aware UTC datetime."""
    return parse_datetime(store.clock_iso)


def now_iso():
    return store.clock_iso


def today():
    return now_dt().date()


# ---------------------------------------------------------------------------
# Parsing / formatting
# ---------------------------------------------------------------------------

def parse_datetime(s):
    """Parse an ISO-8601 datetime (UTC assumed when no offset). Raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    m = _DT_RE.match(s.strip())
    if not m:
        raise ValueError("bad datetime: %r" % s)
    y, mo, d, h, mi, sec = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        digits = frac[1:]
        micro = int((digits + "000000")[:6])
    tz = m.group(8)
    if tz and tz != "Z":
        sign = 1 if tz[0] == "+" else -1
        tzs = tz[1:].replace(":", "")
        off = timedelta(hours=int(tzs[:2]), minutes=int(tzs[2:4]))
        tzinfo = timezone(sign * off)
    else:
        tzinfo = timezone.utc
    dt = datetime(y, mo, d, h, mi, sec, micro, tzinfo=tzinfo)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse an ISO calendar date. Raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    m = _DATE_RE.match(s.strip())
    if not m:
        raise ValueError("bad date: %r" % s)
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def fmt_dt(dt):
    """Format an aware UTC datetime as ISO-8601 with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def fmt_date(d):
    return d.isoformat()


def new_id():
    return str(uuid.uuid4())


def stamp_created():
    """Creation timestamp: logical clock. (format has 3 fractional digits)"""
    return now_iso()


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------

def round_half_up(value, places):
    """Round half-up to the given number of decimal places; returns float."""
    q = Decimal(1).scaleb(-places)
    return float(Decimal(repr(value)).quantize(q, rounding=ROUND_HALF_UP))


def round_half_up_decimal(value, places):
    q = Decimal(1).scaleb(-places)
    return Decimal(repr(value)).quantize(q, rounding=ROUND_HALF_UP)


def round_to_unit_half_up(minutes, unit=15):
    """Round half-up to the nearest whole `unit` minutes; returns int."""
    d = (Decimal(minutes) / Decimal(unit)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(d) * unit


def floor_div_seconds_to_minutes(seconds):
    return int(math.floor(seconds / 60.0))


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def iso_week_key(dt):
    """ISO week key (year, week) for a datetime; weeks run Monday-Sunday."""
    iso = dt.date().isocalendar()
    return (iso[0], iso[1])


def date_of(dt):
    return dt.date()
