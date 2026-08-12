"""Time parsing/formatting, decimal money helpers, body field validation."""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import fail

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-05-01T00:00:00.000Z"""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime. None on failure."""
    if not isinstance(value, str) or not _ISO_RE.match(value):
        return None
    s = value.replace("Z", "+00:00").replace("z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def round_half_up(d):
    """Round a Decimal to integer cents, half-up."""
    return int(Decimal(d).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Request body field extraction / validation. All failures -> ERR_VALIDATION.
# ---------------------------------------------------------------------------

def body(request):
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req(data, name):
    if name not in data or data[name] is None:
        fail("ERR_VALIDATION", f"missing required field: {name}")
    return data[name]


def req_str(data, name):
    v = req(data, name)
    if not isinstance(v, str):
        fail("ERR_VALIDATION", f"field {name} must be a string")
    return v


def opt_str(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    if not isinstance(data[name], str):
        fail("ERR_VALIDATION", f"field {name} must be a string")
    return data[name]


def req_int(data, name, minimum=None):
    v = req(data, name)
    if not is_int(v):
        fail("ERR_VALIDATION", f"field {name} must be an integer")
    if minimum is not None and v < minimum:
        fail("ERR_VALIDATION", f"field {name} out of range")
    return v


def opt_int(data, name, default=None, minimum=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not is_int(v):
        fail("ERR_VALIDATION", f"field {name} must be an integer")
    if minimum is not None and v < minimum:
        fail("ERR_VALIDATION", f"field {name} out of range")
    return v


def req_num(data, name, minimum=None, maximum=None):
    v = req(data, name)
    if not is_num(v):
        fail("ERR_VALIDATION", f"field {name} must be a number")
    if minimum is not None and v < minimum:
        fail("ERR_VALIDATION", f"field {name} out of range")
    if maximum is not None and v > maximum:
        fail("ERR_VALIDATION", f"field {name} out of range")
    return v


def req_dt(data, name):
    v = req(data, name)
    dt = parse_dt(v)
    if dt is None:
        fail("ERR_VALIDATION", f"field {name} must be an ISO 8601 UTC timestamp")
    return dt


def opt_dt(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    dt = parse_dt(data[name])
    if dt is None:
        fail("ERR_VALIDATION", f"field {name} must be an ISO 8601 UTC timestamp")
    return dt


def req_enum(data, name, allowed):
    v = req(data, name)
    if v not in allowed:
        fail("ERR_VALIDATION", f"field {name} must be one of {sorted(allowed)}")
    return v


def opt_enum(data, name, allowed, default=None):
    if name not in data or data[name] is None:
        return default
    if data[name] not in allowed:
        fail("ERR_VALIDATION", f"field {name} must be one of {sorted(allowed)}")
    return data[name]


def opt_bool(data, name, default=False):
    if name not in data or data[name] is None:
        return default
    if not isinstance(data[name], bool):
        fail("ERR_VALIDATION", f"field {name} must be a boolean")
    return data[name]


MINUTES_45 = timedelta(minutes=45)
MINUTES_15 = timedelta(minutes=15)
HOURS_24 = timedelta(hours=24)
