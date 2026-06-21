"""Body-parsing and field-validation helpers.

Well-formedness checks raise ERR_INVALID_REQUEST (PRD §2.8 step 4) unless a more
specific error applies.
"""
from flask import request

import errors


def get_json_body():
    """Return the parsed JSON body as a dict, or {} for an empty body."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        # Body present but unparseable, or not an object.
        if request.data:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Request body is not valid JSON")
        return {}
    if not isinstance(body, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % n)


def require_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or not v.strip():
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % name)
    return v


def require_enum(body, name, allowed):
    v = body.get(name)
    if v not in allowed:
        raise errors.err(
            errors.ERR_INVALID_REQUEST,
            "Field %s must be one of %s" % (name, sorted(allowed)),
        )
    return v


def require_int(body, name, non_negative=False):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    if non_negative and v < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be non-negative" % name)
    return v


def optional_int(body, name, default=None, non_negative=False):
    if name not in body or body[name] is None:
        return default
    return require_int(body, name, non_negative=non_negative)


def require_number(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be a number" % name)
    return v


def optional_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be a boolean" % name)
    return v
