"""Request-body parsing and field-domain validation helpers (priority 12 →
ERR_INVALID_REQUEST per PRD §2.9)."""
from flask import request

import errors
from errors import err


def body():
    """Return the JSON body as a dict, or {} when absent. Malformed JSON or a
    non-object body is a field-domain violation."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise err(errors.ERR_INVALID_REQUEST, "Body must be valid JSON")
    if not isinstance(data, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Body must be a JSON object")
    return data


def require(data, field):
    if field not in data or data[field] is None:
        raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}")
    return data[field]


def invalid(message="Invalid request"):
    raise err(errors.ERR_INVALID_REQUEST, message)


def require_str(data, field):
    v = require(data, field)
    if not isinstance(v, str) or not v.strip():
        invalid(f"{field} must be a non-empty string")
    return v


def require_enum(data, field, allowed):
    v = require(data, field)
    if v not in allowed:
        invalid(f"{field} must be one of {sorted(allowed)}")
    return v


def opt_enum(data, field, allowed, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if v not in allowed:
        invalid(f"{field} must be one of {sorted(allowed)}")
    return v


def require_int(data, field, minimum=None, maximum=None):
    v = require(data, field)
    if isinstance(v, bool) or not isinstance(v, int):
        invalid(f"{field} must be an integer")
    if minimum is not None and v < minimum:
        invalid(f"{field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        invalid(f"{field} must be <= {maximum}")
    return v


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        return default
    return require_int(data, field, minimum=minimum, maximum=maximum)


def require_number(data, field, minimum=None):
    v = require(data, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        invalid(f"{field} must be a number")
    if minimum is not None and v < minimum:
        invalid(f"{field} must be >= {minimum}")
    return v


def opt_number(data, field, default=None, minimum=None):
    if field not in data or data[field] is None:
        return default
    return require_number(data, field, minimum=minimum)


def opt_bool(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, bool):
        invalid(f"{field} must be a boolean")
    return v
