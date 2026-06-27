"""Request-body validation helpers (ERR_INVALID_REQUEST, priority 17)."""
from decimal import Decimal, InvalidOperation

from errors import err


def get_body():
    from flask import request
    if request.data and request.data.strip():
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
        if body is None:
            raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
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


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a string")
    return v


def req_int(body, field, minimum=None):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}")
    return v


def opt_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return v


def req_bool(body, field):
    v = require(body, field)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}")
    return v


def opt_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    return req_enum(body, field, allowed)


def req_number(body, field):
    """Accept int or float; return Decimal. Used for share quantities / per-share rates."""
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a number")
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a number")
