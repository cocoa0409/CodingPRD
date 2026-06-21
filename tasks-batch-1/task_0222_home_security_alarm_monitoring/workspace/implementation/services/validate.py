"""Request-body parsing/validation helpers (ERR_VALIDATION, scaffold priority 17).

These raise ApiError(ERR_VALIDATION, 422) on malformed bodies: missing required
field, wrong type, bad enum member, or out-of-range numeric input.
"""
from flask import request

from errors import err, ERR_VALIDATION


def get_body():
    """Return the JSON body as a dict (or {} when empty). Malformed JSON -> 422."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err(ERR_VALIDATION, "Request body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_VALIDATION, "Request body must be a JSON object")
    return data


def require_str(body, field):
    if field not in body:
        raise err(ERR_VALIDATION, "Missing required field: %s" % field)
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise err(ERR_VALIDATION, "Field %s must be a non-empty string" % field)
    return v


def require_enum(body, field, allowed):
    v = require_str(body, field)
    if v not in allowed:
        raise err(ERR_VALIDATION, "Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def require_int(body, field, minimum=None, maximum=None):
    if field not in body:
        raise err(ERR_VALIDATION, "Missing required field: %s" % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_VALIDATION, "Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise err(ERR_VALIDATION, "Field %s must be >= %s" % (field, minimum))
    if maximum is not None and v > maximum:
        raise err(ERR_VALIDATION, "Field %s must be <= %s" % (field, maximum))
    return v


def require_bool(body, field):
    if field not in body:
        raise err(ERR_VALIDATION, "Missing required field: %s" % field)
    v = body[field]
    if not isinstance(v, bool):
        raise err(ERR_VALIDATION, "Field %s must be a boolean" % field)
    return v


def optional_int(body, field, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return None
    return require_int(body, field, minimum, maximum)


def optional_enum(body, field, allowed):
    if field not in body or body[field] is None:
        return None
    return require_enum(body, field, allowed)
