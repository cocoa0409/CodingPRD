"""Request body parsing & field validation helpers (PRD §2.6).

ERR_INVALID_REQUEST (400): malformed body, missing required field, invalid enum.
ERR_VALIDATION (422): semantically invalid but well-formed field value.
"""
from flask import request

from errors import err


def get_body():
    """Parse JSON body; tolerate empty body as {}."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body.")
    if data is None:
        # Body present but not valid JSON.
        if request.data.strip():
            raise err("ERR_INVALID_REQUEST", "Malformed JSON body.")
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object.")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: {}.".format(field))
    return body[field]


def require_string(body, field, allow_empty=False):
    val = require(body, field)
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "Field {} must be a string.".format(field))
    if not allow_empty and val.strip() == "":
        raise err("ERR_VALIDATION", "Field {} must be non-empty.".format(field))
    return val


def require_int(body, field):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field {} must be an integer.".format(field))
    return val


def require_number(body, field):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field {} must be a number.".format(field))
    return val


def require_bool(body, field):
    val = require(body, field)
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field {} must be a boolean.".format(field))
    return val


def require_enum(body, field, allowed):
    val = require(body, field)
    if not isinstance(val, str) or val not in allowed:
        raise err(
            "ERR_INVALID_REQUEST",
            "Field {} must be one of {}.".format(field, sorted(allowed)),
        )
    return val


def optional_string(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "Field {} must be a string.".format(field))
    return val


def optional_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field {} must be a boolean.".format(field))
    return val
