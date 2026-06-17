"""Request body parsing and field validation helpers.

Body-shape validation runs FIRST (PRD §2.8 priority 0): required fields present,
types/enums valid, numeric ranges satisfied -> ERR_INVALID_REQUEST (400) before
auth or business logic.
"""
from flask import request

import errors
from errors import err


def get_json_body():
    """Parse the request JSON body. Missing body is treated as an empty object
    (so endpoints with no required fields work with no body). A body present but
    not a JSON object is ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise err(errors.ERR_INVALID_REQUEST, "Malformed JSON body")
    if data is None:
        # data present but unparseable
        raise err(errors.ERR_INVALID_REQUEST, "Malformed JSON body")
    if not isinstance(data, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % n)


def require_string(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name)
        return None
    v = body[name]
    if not isinstance(v, str) or v.strip() == "":
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % name)
    return v


def require_int(body, name, required=True, minimum=None, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name)
        return default
    v = body[name]
    # reject bools (which are ints in python) and non-ints
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be >= %s" % (name, minimum))
    return v


def require_number(body, name, required=True, minimum=None, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name)
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a number" % name)
    if minimum is not None and v < minimum:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be >= %s" % (name, minimum))
    return v


def require_enum(body, name, choices, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name)
        return default
    v = body[name]
    if v not in choices:
        raise err(errors.ERR_INVALID_REQUEST,
                  "Field %s must be one of %s" % (name, sorted(choices)))
    return v
