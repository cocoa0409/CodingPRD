"""Body parsing and field validation helpers (PRD §2.8)."""

from flask import request
from errors import err, ERR_INVALID_REQUEST


def get_body():
    """Return the JSON body as a dict (empty dict when no body)."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Body must be a JSON object")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    return body[field]


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        raise err(ERR_INVALID_REQUEST, f"{field} must be a non-empty string")
    return val


def require_number(body, field):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(ERR_INVALID_REQUEST, f"{field} must be numeric")
    return val


def require_int(body, field):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an integer")
    return val


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a boolean")
    return val


def optional_number(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(ERR_INVALID_REQUEST, f"{field} must be numeric")
    return val


def optional_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an integer")
    return val


def require_enum(body, field, choices):
    val = require(body, field)
    if val not in choices:
        raise err(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(choices)}")
    return val
