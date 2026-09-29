"""Request-shape gate (PRD 2.8): body parsing, typed field readers, pagination."""
from decimal import Decimal, InvalidOperation

from flask import request

import clock
from errors import ApiError

_MISSING = object()


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def body():
    """Parse the JSON body. Absent body is treated as an empty object."""
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body must be valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def raw_body():
    """Best-effort body read that never raises; used for pre-schema ownership checks."""
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def present(b, key):
    return key in b and b[key] is not None


def _get(b, key, required):
    if key not in b or b[key] is None:
        if required:
            bad("Field '%s' is required." % key)
        return _MISSING
    return b[key]


def field_str(b, key, required=True, default=None, allow_empty=False):
    v = _get(b, key, required)
    if v is _MISSING:
        return default
    if not isinstance(v, str):
        bad("Field '%s' must be a string." % key)
    if not allow_empty and v.strip() == "":
        bad("Field '%s' must be a non-empty string." % key)
    return v


def field_int(b, key, required=True, default=None, minimum=None, maximum=None):
    v = _get(b, key, required)
    if v is _MISSING:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and v < minimum:
        bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and v > maximum:
        bad("Field '%s' must be <= %s." % (key, maximum))
    return v


def field_num(b, key, required=True, default=None, minimum=None, maximum=None,
              exclusive_min=None):
    v = _get(b, key, required)
    if v is _MISSING:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float, Decimal)):
        bad("Field '%s' must be a number." % key)
    try:
        d = Decimal(repr(v)) if isinstance(v, float) else Decimal(v)
    except (InvalidOperation, ValueError):
        bad("Field '%s' must be a number." % key)
    if minimum is not None and d < Decimal(str(minimum)):
        bad("Field '%s' must be >= %s." % (key, minimum))
    if exclusive_min is not None and d <= Decimal(str(exclusive_min)):
        bad("Field '%s' must be > %s." % (key, exclusive_min))
    if maximum is not None and d > Decimal(str(maximum)):
        bad("Field '%s' must be <= %s." % (key, maximum))
    return d


def field_bool(b, key, required=True, default=None):
    v = _get(b, key, required)
    if v is _MISSING:
        return default
    if not isinstance(v, bool):
        bad("Field '%s' must be a boolean." % key)
    return v


def field_enum(b, key, allowed, required=True, default=None):
    v = _get(b, key, required)
    if v is _MISSING:
        return default
    if not isinstance(v, str) or v not in allowed:
        bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return v


def field_date(b, key, required=True, default=None):
    """Returns (raw_string, date) -- the raw string is echoed back verbatim."""
    v = _get(b, key, required)
    if v is _MISSING:
        return default, None
    if not isinstance(v, str):
        bad("Field '%s' must be an ISO 8601 date string." % key)
    parsed = clock.parse_date(v)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 date string." % key)
    return v, parsed


def field_instant(b, key, required=True, default=None):
    """Returns (raw_string, datetime)."""
    v = _get(b, key, required)
    if v is _MISSING:
        return default, None
    if not isinstance(v, str):
        bad("Field '%s' must be an ISO 8601 timestamp." % key)
    parsed = clock.parse_instant(v)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 timestamp." % key)
    return v, parsed


def state_code(b, key, required=True, default=None):
    v = field_str(b, key, required=required, default=default)
    if v is None:
        return None
    if len(v) != 2 or not v.isalpha() or v != v.upper():
        bad("Field '%s' must be exactly two uppercase letters." % key)
    return v


def zip_code(b, key, required=True, default=None):
    v = field_str(b, key, required=required, default=default)
    if v is None:
        return None
    if len(v) != 5 or not v.isdigit():
        bad("Field '%s' must be exactly five digits." % key)
    return v


def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def page(rows, limit, offset):
    return rows[offset:offset + limit]


def query_enum(name, allowed):
    v = request.args.get(name)
    if v is None or v == "":
        return None
    if v not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return v


def query_bool(name):
    v = request.args.get(name)
    if v is None or v == "":
        return None
    low = v.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    bad("Query parameter '%s' must be a boolean." % name)
