"""Shared helpers: decimal rounding, ISO-8601 timestamps, primitive validation."""
import math
import random
import re
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError

ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def D(value):
    """Coerce anything numeric-ish into an exact Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    return Decimal(str(value))


def round_half_up(value, places=0):
    """Decimal ROUND_HALF_UP at the requested number of decimal places."""
    quant = Decimal(1).scaleb(-int(places))
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(round_half_up(value, 0))


def num(value, places):
    """Round then hand back a JSON-friendly float at fixed scale."""
    return float(round_half_up(value, places))


# ---------------------------------------------------------------- timestamps
def parse_iso(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    m = ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        micro = int(round(float(frac) * 1000000))
    offset = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro,
                        tzinfo=timezone.utc)
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        base = base - sign * delta
    return base


def format_iso(dt):
    """ISO-8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def wall_now_iso():
    return format_iso(datetime.now(timezone.utc))


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def minutes_between(start_dt, end_dt):
    return int((end_dt - start_dt).total_seconds() // 60)


def seconds_between(start_dt, end_dt):
    return (end_dt - start_dt).total_seconds()


def date_key(dt):
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02d" % (dt.year, dt.month, dt.day)


# ------------------------------------------------------------- body plumbing
def bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def get_body():
    """Request body as a dict; anything that is not a JSON object is rejected."""
    from flask import request
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=True)
    except Exception:
        parsed = None
    if parsed is None:
        raise bad_request("request body must be a JSON object")
    if not isinstance(parsed, dict):
        raise bad_request("request body must be a JSON object")
    return parsed


def require_fields(body, names):
    for name in names:
        if name not in body or body[name] is None:
            raise bad_request("%s is required" % name)


def want_str(body, name, min_len=1, max_len=None, required=True):
    if name not in body or body[name] is None:
        if required:
            raise bad_request("%s is required" % name)
        return None
    value = body[name]
    if not isinstance(value, str):
        raise bad_request("%s must be a string" % name)
    if len(value) < min_len:
        raise bad_request("%s must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad_request("%s must be at most %d characters" % (name, max_len))
    return value


def want_pattern(body, name, pattern, required=True, min_len=1, max_len=None):
    value = want_str(body, name, min_len=min_len, max_len=max_len,
                     required=required)
    if value is None:
        return None
    if not re.match(pattern, value):
        raise bad_request("%s has an invalid format" % name)
    return value


def want_enum(body, name, allowed, required=True):
    if name not in body or body[name] is None:
        if required:
            raise bad_request("%s is required" % name)
        return None
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        raise bad_request("%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def want_int(body, name, minimum=None, maximum=None, required=True):
    if name not in body or body[name] is None:
        if required:
            raise bad_request("%s is required" % name)
        return None
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise bad_request("%s must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("%s must be at most %d" % (name, maximum))
    return value


def want_number(body, name, minimum=None, maximum=None, required=True):
    if name not in body or body[name] is None:
        if required:
            raise bad_request("%s is required" % name)
        return None
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("%s must be a number" % name)
    dec = D(value)
    if minimum is not None and dec < D(minimum):
        raise bad_request("%s must be at least %s" % (name, minimum))
    if maximum is not None and dec > D(maximum):
        raise bad_request("%s must be at most %s" % (name, maximum))
    return dec


def want_bool(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise bad_request("%s is required" % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise bad_request("%s must be a boolean" % name)
    return value


def want_iso(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            raise bad_request("%s is required" % name)
        return None
    parsed = parse_iso(body[name])
    if parsed is None:
        raise bad_request("%s must be an ISO-8601 UTC timestamp" % name)
    return parsed


def want_str_list(body, name, required=True, min_items=0, allow_empty=False):
    if name not in body or body[name] is None:
        if required:
            raise bad_request("%s is required" % name)
        return None
    value = body[name]
    if not isinstance(value, list):
        raise bad_request("%s must be an array" % name)
    if len(value) < min_items:
        raise bad_request("%s must contain at least %d item(s)" % (name, min_items))
    for item in value:
        if not isinstance(item, str) or (not allow_empty and not item):
            raise bad_request("%s must contain only non-empty strings" % name)
    return value


def as_dt(value):
    if isinstance(value, str):
        return parse_iso(value)
    return value


def whole_days_between(start, end):
    """Floored whole days between two instants (ISO strings or datetimes)."""
    start_dt = as_dt(start)
    end_dt = as_dt(end)
    if start_dt is None or end_dt is None:
        return 0
    return int(math.floor((end_dt - start_dt).total_seconds() / 86400.0))
