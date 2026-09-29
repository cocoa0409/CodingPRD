"""Schema validation helpers - every failure here is rank 7 ERR_VALIDATION (422)."""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from errors import ApiError

_MISSING = object()

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def bad(message):
    raise ApiError("ERR_VALIDATION", 422, message)


def body_dict(raw):
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        bad("Request body must be a JSON object")
    return raw


def reject_computed(body, forbidden):
    for key in forbidden:
        if key in body:
            bad("Field '%s' is server-managed and cannot be supplied" % key)


def parse_dt(value, field):
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 timestamp string" % field)
    m = _ISO_RE.match(value.strip())
    if not m:
        bad("Field '%s' must be an ISO 8601 timestamp string" % field)
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    tz = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        bad("Field '%s' is not a valid timestamp" % field)
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        tz = tz[1:].replace(":", "")
        offset_minutes = int(tz[:2]) * 60 + int(tz[2:])
        from datetime import timedelta

        dt = dt - sign * timedelta(minutes=offset_minutes)
    return dt


def get(body, field, required=False, default=None):
    if field not in body or body[field] is None:
        if required:
            bad("Field '%s' is required" % field)
        return default
    return body[field]


def field_present(body, field):
    return field in body and body[field] is not None


def as_str(body, field, required=False, default=None, min_len=1, max_len=None):
    value = get(body, field, required, _MISSING)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        bad("Field '%s' must be a string" % field)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters" % (field, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters" % (field, max_len))
    return value


def as_enum(body, field, allowed, required=False, default=None):
    value = get(body, field, required, _MISSING)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s" % (field, ", ".join(sorted(allowed))))
    return value


def as_int(body, field, required=False, default=None, minimum=None, maximum=None):
    value = get(body, field, required, _MISSING)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer" % field)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s" % (field, maximum))
    return value


def as_dec(body, field, required=False, default=None, minimum=None, maximum=None,
           exclusive_minimum=None):
    value = get(body, field, required, _MISSING)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        bad("Field '%s' must be a number" % field)
    try:
        value = Decimal(str(value))
    except InvalidOperation:
        bad("Field '%s' must be a number" % field)
    if not value.is_finite():
        bad("Field '%s' must be a finite number" % field)
    if minimum is not None and value < Decimal(str(minimum)):
        bad("Field '%s' must be >= %s" % (field, minimum))
    if exclusive_minimum is not None and value <= Decimal(str(exclusive_minimum)):
        bad("Field '%s' must be > %s" % (field, exclusive_minimum))
    if maximum is not None and value > Decimal(str(maximum)):
        bad("Field '%s' must be <= %s" % (field, maximum))
    return value


def as_bool(body, field, required=False, default=None):
    value = get(body, field, required, _MISSING)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean" % field)
    return value


def as_dt(body, field, required=False, default=None):
    value = get(body, field, required, _MISSING)
    if value is _MISSING:
        return default
    return parse_dt(value, field)


def as_code_list(body, field, vocabulary, required=False, default=None, allow_empty=False):
    value = get(body, field, required, _MISSING)
    if value is _MISSING:
        return default
    if not isinstance(value, list):
        bad("Field '%s' must be an array" % field)
    if not value and not allow_empty:
        bad("Field '%s' must not be empty" % field)
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in vocabulary:
            bad("Field '%s' contains an unrecognised code" % field)
        if item in seen:
            bad("Field '%s' contains duplicate codes" % field)
        seen.add(item)
    return list(value)


def as_id(body, field, required=False):
    """Reference-shaped field: must be a string when present."""
    value = get(body, field, required, _MISSING)
    if value is _MISSING:
        return None
    if not isinstance(value, str) or not value:
        bad("Field '%s' must be a non-empty string identifier" % field)
    return value
