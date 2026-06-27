"""Body-parsing / well-formedness helpers (priority-5 ERR_INVALID_REQUEST;
priority-? ERR_VALIDATION for semantic field violations that parse)."""
from flask import request

from errors import err


def get_body():
    if request.data and request.data.strip():
        body = request.get_json(silent=True)
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


def require_str(body, field, allow_empty=False):
    val = require(body, field)
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a string")
    if not allow_empty and val == "":
        raise err("ERR_INVALID_REQUEST", f"{field} must be non-empty")
    return val


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a string")
    return val


def require_enum(body, field, allowed):
    val = require(body, field)
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", f"{field} must be one of {sorted(allowed)}")
    return val


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", f"{field} must be one of {sorted(allowed)}")
    return val


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def require_int(body, field, minimum=None):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an integer")
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", f"{field} must be >= {minimum}")
    return val


def opt_int(body, field, default=None, minimum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an integer")
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", f"{field} must be >= {minimum}")
    return val


def require_number(body, field, gt=None, ge=None):
    val = require(body, field)
    if not _is_number(val):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a number")
    if gt is not None and not val > gt:
        raise err("ERR_INVALID_REQUEST", f"{field} must be > {gt}")
    if ge is not None and not val >= ge:
        raise err("ERR_INVALID_REQUEST", f"{field} must be >= {ge}")
    return val


def opt_number(body, field, default=None, ge=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not _is_number(val):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a number")
    if ge is not None and not val >= ge:
        raise err("ERR_INVALID_REQUEST", f"{field} must be >= {ge}")
    return val


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a boolean")
    return val
