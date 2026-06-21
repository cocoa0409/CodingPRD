"""Body-shape validation helpers (ERR_INVALID_REQUEST, priority 5)."""
from flask import request

import errors


def get_body():
    """Return the JSON body as a dict, or {} when absent. Malformed JSON or a
    non-object body -> ERR_INVALID_REQUEST."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    return body[field]


def require_str(body, field):
    v = require(body, field)
    if not isinstance(v, str) or v.strip() == "":
        raise errors.invalid_request(f"Field {field} must be a non-empty string")
    return v


def require_int(body, field, minimum=None, maximum=None):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request(f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise errors.invalid_request(f"Field {field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise errors.invalid_request(f"Field {field} must be <= {maximum}")
    return v


def optional_int(body, field, minimum=None, maximum=None, default=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum, maximum)


def require_bool(body, field):
    v = require(body, field)
    if not isinstance(v, bool):
        raise errors.invalid_request(f"Field {field} must be a boolean")
    return v


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    return require_bool(body, field)


def require_enum(body, field, allowed):
    v = require_str(body, field)
    if v not in allowed:
        raise errors.invalid_request(f"Field {field} must be one of {sorted(allowed)}")
    return v
