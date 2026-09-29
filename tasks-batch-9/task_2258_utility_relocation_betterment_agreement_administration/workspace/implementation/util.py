"""Shared low-level helpers: time parsing/formatting and rounding discipline."""
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- time --------

DAY = timedelta(days=1)


def parse_iso(value):
    """Parse an ISO 8601 instant.  Returns an aware UTC datetime or None."""
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
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_iso(datetime.now(timezone.utc))


def days_between(start_dt, end_dt):
    """Whole days spanned by [start, end); window_end is exclusive."""
    return (end_dt - start_dt).days


def ceil_days(delta):
    """Whole days, rounded up, of a timedelta."""
    return int(math.ceil(delta.total_seconds() / 86400.0))


# ------------------------------------------------------------ rounding --------

def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(repr(value))


def round_half_up(value, places=0):
    """Round half away from zero to `places` decimal places (Decimal result)."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    """Round half up to whole units and return a Python int."""
    return int(round_half_up(value, 0))


def decimal_places(value):
    """Number of decimal places a numeric literal carries."""
    d = dec(value).normalize()
    exponent = d.as_tuple().exponent
    if not isinstance(exponent, int):
        return 0
    return max(0, -exponent)


def num_out(value):
    """Serialise a stored numeric (Decimal/int/float) for JSON."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            # keep integral ratios as floats so the JSON type stays numeric
            return float(value)
        return float(value)
    return value
