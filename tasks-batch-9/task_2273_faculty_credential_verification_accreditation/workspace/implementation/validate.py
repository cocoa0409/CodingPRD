"""Rung 4 (shape) helpers, pagination parsing and query-filter parsing."""

from decimal import Decimal, InvalidOperation

from flask import request

import util
from errors import ApiError

_MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def present(payload, name):
    return name in payload and payload[name] is not None


# ------------------------------------------------------------------ scalars
def req_str(payload, name, allow_empty=False):
    if not present(payload, name):
        bad("Field '%s' is required." % name)
    value = payload[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if not allow_empty and not value.strip():
        bad("Field '%s' must not be empty." % name)
    return value


def opt_str(payload, name, default=None, allow_empty=True):
    if not present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if not allow_empty and not value.strip():
        bad("Field '%s' must not be empty." % name)
    return value


def req_enum(payload, name, allowed):
    value = req_str(payload, name)
    if value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(payload, name, allowed, default=None):
    if not present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def _as_int(value, name):
    if isinstance(value, bool):
        bad("Field '%s' must be an integer." % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    bad("Field '%s' must be an integer." % name)


def req_int(payload, name, minimum=None, maximum=None):
    if not present(payload, name):
        bad("Field '%s' is required." % name)
    value = _as_int(payload[name], name)
    _check_bounds(value, name, minimum, maximum)
    return value


def opt_int(payload, name, default=None, minimum=None, maximum=None):
    if not present(payload, name):
        return default
    value = _as_int(payload[name], name)
    _check_bounds(value, name, minimum, maximum)
    return value


def _check_bounds(value, name, minimum, maximum):
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (name, maximum))


def _as_dec(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        bad("Field '%s' must be a number." % name)
    try:
        return util.dec(value)
    except (InvalidOperation, ValueError):
        bad("Field '%s' must be a number." % name)


def req_num(payload, name, minimum=None, maximum=None, exclusive_min=None):
    if not present(payload, name):
        bad("Field '%s' is required." % name)
    value = _as_dec(payload[name], name)
    if exclusive_min is not None and value <= Decimal(exclusive_min):
        bad("Field '%s' must be greater than %s." % (name, exclusive_min))
    _check_bounds(value, name, minimum, maximum)
    return value


def opt_num(payload, name, default=None, minimum=None, maximum=None, exclusive_min=None):
    if not present(payload, name):
        return default
    value = _as_dec(payload[name], name)
    if exclusive_min is not None and value <= Decimal(exclusive_min):
        bad("Field '%s' must be greater than %s." % (name, exclusive_min))
    _check_bounds(value, name, minimum, maximum)
    return value


def req_bool(payload, name):
    if not present(payload, name):
        bad("Field '%s' is required." % name)
    value = payload[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def opt_bool(payload, name, default=None):
    if not present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def req_date(payload, name):
    text = req_str(payload, name)
    parsed = util.parse_date(text)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 date." % name)
    return parsed


def opt_date(payload, name, default=None):
    if not present(payload, name):
        return default
    text = payload[name]
    if not isinstance(text, str):
        bad("Field '%s' must be an ISO 8601 date." % name)
    parsed = util.parse_date(text)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 date." % name)
    return parsed


def req_str_array(payload, name, allowed=None, allow_absent=False, default=None):
    if not present(payload, name):
        if allow_absent:
            return list(default or [])
        bad("Field '%s' is required." % name)
    value = payload[name]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    out = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            bad("Field '%s' must contain non-empty strings." % name)
        if allowed is not None and item not in allowed:
            bad("Field '%s' must contain only %s." % (name, ", ".join(allowed)))
        out.append(item)
    return out


# --------------------------------------------------------------- pagination
def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(str(limit_raw).strip())
        except ValueError:
            bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if offset_raw is not None:
        try:
            offset = int(str(offset_raw).strip())
        except ValueError:
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must not be negative.")
    return limit, offset


def q_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def q_enum(name, allowed):
    value = q_str(name)
    if value is None:
        return None
    if value not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def q_bool(name):
    value = q_str(name)
    if value is None:
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("Query parameter '%s' must be a boolean." % name)


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
