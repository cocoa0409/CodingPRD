"""Request-body parsing and field validation helpers.

Generic well-formedness failures surface ERR_INVALID_REQUEST (priority 18, the
lowest-priority / last-resort check).
"""
from flask import request

from errors import err


def get_json_body():
    """Return the parsed JSON object, or {} when body is empty. Malformed -> ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object.")
    return body


def require(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}.")
    return body[field]


def require_str(body, field, allow_empty=False):
    val = require(body, field)
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a string.")
    if not allow_empty and val.strip() == "":
        raise err("ERR_INVALID_REQUEST", f"{field} must be non-empty.")
    return val


def optional_str(body, field, default=""):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a string.")
    return val


def require_int(body, field, minimum=None):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an integer.")
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", f"{field} must be >= {minimum}.")
    return val


def optional_int(body, field, default=None, minimum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an integer.")
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", f"{field} must be >= {minimum}.")
    return val


def require_enum(body, field, allowed):
    val = require(body, field)
    if not isinstance(val, str) or val not in allowed:
        raise err("ERR_INVALID_REQUEST", f"{field} must be one of {sorted(allowed)}.")
    return val
