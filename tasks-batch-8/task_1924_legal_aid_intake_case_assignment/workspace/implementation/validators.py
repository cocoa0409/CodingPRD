"""Request body parsing and field validators (PRD section 2.7 step 5)."""
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ERR_INVALID_REQUEST, fail


def body():
    """Parse the request body as a JSON object; empty body -> {}."""
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        fail(ERR_INVALID_REQUEST, "Request body must be valid JSON")
    if not isinstance(data, dict):
        fail(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def check_allowed(b, allowed):
    for k in b:
        if k not in allowed:
            fail(ERR_INVALID_REQUEST, "Unknown field: {}".format(k))


def _missing(name):
    fail(ERR_INVALID_REQUEST, "Missing required field: {}".format(name))


def req_str(b, name):
    v = b.get(name)
    if v is None:
        _missing(name)
    if not isinstance(v, str):
        fail(ERR_INVALID_REQUEST, "Field {} must be a string".format(name))
    return v


def opt_str(b, name, default=None):
    v = b.get(name)
    if v is None:
        return default
    if not isinstance(v, str):
        fail(ERR_INVALID_REQUEST, "Field {} must be a string".format(name))
    return v


def _check_int(name, v, min_v, max_v):
    if isinstance(v, bool) or not isinstance(v, int):
        fail(ERR_INVALID_REQUEST, "Field {} must be an integer".format(name))
    if min_v is not None and v < min_v:
        fail(ERR_INVALID_REQUEST, "Field {} is below its minimum".format(name))
    if max_v is not None and v > max_v:
        fail(ERR_INVALID_REQUEST, "Field {} exceeds its maximum".format(name))
    return v


def req_int(b, name, min_v=None, max_v=None):
    v = b.get(name)
    if v is None:
        _missing(name)
    return _check_int(name, v, min_v, max_v)


def opt_int(b, name, default=None, min_v=None, max_v=None):
    v = b.get(name)
    if v is None:
        return default
    return _check_int(name, v, min_v, max_v)


def req_bool(b, name):
    v = b.get(name)
    if v is None:
        _missing(name)
    if not isinstance(v, bool):
        fail(ERR_INVALID_REQUEST, "Field {} must be a boolean".format(name))
    return v


def opt_bool(b, name, default=None):
    v = b.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        fail(ERR_INVALID_REQUEST, "Field {} must be a boolean".format(name))
    return v


def req_enum(b, name, values):
    v = b.get(name)
    if v is None:
        _missing(name)
    if not isinstance(v, str) or v not in values:
        fail(ERR_INVALID_REQUEST,
             "Field {} must be one of {}".format(name, ", ".join(values)))
    return v


def opt_enum(b, name, values, default=None):
    v = b.get(name)
    if v is None:
        return default
    if not isinstance(v, str) or v not in values:
        fail(ERR_INVALID_REQUEST,
             "Field {} must be one of {}".format(name, ", ".join(values)))
    return v


def _check_list(name, v, enum_values=None):
    if not isinstance(v, list):
        fail(ERR_INVALID_REQUEST, "Field {} must be an array".format(name))
    for item in v:
        if not isinstance(item, str):
            fail(ERR_INVALID_REQUEST,
                 "Field {} must contain only strings".format(name))
        if enum_values is not None and item not in enum_values:
            fail(ERR_INVALID_REQUEST,
                 "Field {} contains an invalid value".format(name))
    return list(v)


def req_list(b, name, enum_values=None):
    v = b.get(name)
    if v is None:
        _missing(name)
    return _check_list(name, v, enum_values)


def opt_list(b, name, default=None, enum_values=None):
    v = b.get(name)
    if v is None:
        return default
    return _check_list(name, v, enum_values)


def req_number(b, name):
    """Parse a JSON number into Decimal (booleans rejected)."""
    v = b.get(name)
    if v is None:
        _missing(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail(ERR_INVALID_REQUEST, "Field {} must be a number".format(name))
    try:
        return Decimal(str(v))
    except InvalidOperation:
        fail(ERR_INVALID_REQUEST, "Field {} must be a number".format(name))


def req_date(b, name):
    """Validate an ISO date string (YYYY-MM-DD); returns the raw string."""
    v = b.get(name)
    if v is None:
        _missing(name)
    _parse_date(v, name)
    return v


def _parse_date(v, name):
    if not isinstance(v, str):
        fail(ERR_INVALID_REQUEST, "Field {} must be an ISO date string".format(name))
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        fail(ERR_INVALID_REQUEST,
             "Field {} must be a valid ISO date (YYYY-MM-DD)".format(name))


def as_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def parse_iso_datetime(v, name="to_iso8601"):
    if not isinstance(v, str):
        fail(ERR_INVALID_REQUEST, "Field {} must be an ISO 8601 string".format(name))
    s = v.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        fail(ERR_INVALID_REQUEST,
             "Field {} must be a valid ISO 8601 datetime".format(name))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def pagination_params():
    """limit: default 10, clamped to [1, 100]; offset: default 0, clamped >= 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(100, limit))
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)
    return limit, offset
