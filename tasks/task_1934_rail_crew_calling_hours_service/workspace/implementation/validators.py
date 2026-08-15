"""Request-body well-formedness validation (validation priority 0)."""
import json

from flask import request

from db import parse_dt
from errors import ApiError, ERR_INVALID_REQUEST


def _bad(message):
    raise ApiError(ERR_INVALID_REQUEST, 400, message)


def body():
    """Parse the JSON request body. Empty body -> {}. Malformed -> 400."""
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        _bad("Request body is not valid JSON.")
    if not isinstance(data, dict):
        _bad("Request body must be a JSON object.")
    return data


def req_str(data, name):
    v = data.get(name)
    if not isinstance(v, str) or not v.strip():
        _bad("Field '%s' is required and must be a non-empty string." % name)
    return v


def opt_str(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, str) or not v.strip():
        _bad("Field '%s' must be a non-empty string." % name)
    return v


def req_int(data, name, min_value=None):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad("Field '%s' is required and must be an integer." % name)
    if min_value is not None and v < min_value:
        _bad("Field '%s' must be >= %d." % (name, min_value))
    return v


def opt_int(data, name, default=None, min_value=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        _bad("Field '%s' must be an integer." % name)
    if min_value is not None and v < min_value:
        _bad("Field '%s' must be >= %d." % (name, min_value))
    return v


def req_dt(data, name):
    v = data.get(name)
    dt = parse_dt(v)
    if dt is None:
        _bad("Field '%s' is required and must be an ISO 8601 datetime." % name)
    return dt


def req_enum(data, name, allowed):
    v = data.get(name)
    if not isinstance(v, str) or v not in allowed:
        _bad("Field '%s' must be one of: %s." % (name, ", ".join(allowed)))
    return v


def opt_enum(data, name, allowed, default=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, str) or v not in allowed:
        _bad("Field '%s' must be one of: %s." % (name, ", ".join(allowed)))
    return v
