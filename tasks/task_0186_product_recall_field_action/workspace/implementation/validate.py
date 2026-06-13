"""Request-body parsing/validation helpers (priority 4: ERR_INVALID_REQUEST)."""
from errors import err


def get_body():
    from flask import request
    if request.data and request.data.strip():
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            body = None
        if body is None:
            raise err("ERR_INVALID_REQUEST", "Body is not valid JSON")
        if not isinstance(body, dict):
            raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
        return body
    return {}


def require(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    return body[field]


def req_str(body, field):
    v = require(body, field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string")
    return v


def req_enum(body, field, allowed):
    v = require(body, field)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}")
    return v


def req_int(body, field, minimum=None):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}")
    return v


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    return v


def req_bool(body, field):
    v = require(body, field)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return v


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return v


def req_str_field(body, field):
    return req_str(body, field)
