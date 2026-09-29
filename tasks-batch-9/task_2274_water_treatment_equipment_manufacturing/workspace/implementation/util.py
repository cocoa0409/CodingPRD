"""Numeric / temporal helpers.

Rounding contract (PRD 2.6): "round" means ROUND_HALF_UP everywhere unless a
rule says otherwise.  Money is always a whole-cent integer.  Some quantities
are deliberately floored (whole 30-day months, whole delay days, whole booked
minutes) and some deliberately ceiled (process-selection cost terms, skid
footprint).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR

SECONDS_PER_30_DAY_MONTH = 2592000
SECONDS_PER_DAY = 86400


def D(value):
    """Decimal from int / float / str / Decimal without binary float noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value, places=0):
    q = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    """round half up to a whole integer (returns int)."""
    return int(D(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def ceil_int(value):
    return int(D(value).quantize(Decimal(1), rounding=ROUND_CEILING))


def floor_int(value):
    return int(D(value).quantize(Decimal(1), rounding=ROUND_FLOOR))


def num(value, places=None):
    """JSON-serialisable number.  Decimals become floats (ints stay ints)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    d = D(value)
    if places is not None:
        d = round_half_up(d, places)
    return float(d)


# ---------------------------------------------------------------- datetimes --

def parse_dt(text):
    """Parse an ISO 8601 UTC instant.  Returns an aware datetime or None."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_norm(text):
    """Normalise a client-supplied instant to the canonical output format."""
    dt = parse_dt(text)
    return format_dt(dt) if dt else None


def dt_of(stored):
    """Stored ISO string -> aware datetime."""
    return parse_dt(stored) if stored else None


def seconds_between(start, end):
    """end - start in (possibly negative, fractional) seconds."""
    return D((end - start).total_seconds())


def add_days(dt, days):
    return dt + timedelta(days=days)


def whole_30_day_months(start, end):
    """Whole pinned 30-day months elapsed, floored at 0 for negatives."""
    secs = seconds_between(start, end)
    if secs <= 0:
        return 0
    return floor_int(secs / Decimal(SECONDS_PER_30_DAY_MONTH))


def whole_days(start, end):
    secs = seconds_between(start, end)
    if secs <= 0:
        return 0
    return floor_int(secs / Decimal(SECONDS_PER_DAY))


def whole_minutes(start, end):
    secs = seconds_between(start, end)
    if secs <= 0:
        return 0
    return floor_int(secs / Decimal(60))
