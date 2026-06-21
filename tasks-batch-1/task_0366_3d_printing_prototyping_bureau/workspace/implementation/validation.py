"""Request body parsing and well-formedness validation (priority 5).

ERR_INVALID_REQUEST (422) covers: missing required field, ill-typed field,
invalid enum member, quantity < 1, non-positive numeric.
"""

from flask import request

import errors


def get_body():
    """Return the JSON body as a dict. A missing/empty body is treated as {}.

    A body that is present but not a JSON object is ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Body must be a JSON object")
    return data


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise errors.invalid_request("Missing or invalid field: %s" % field)
    return v


def require_enum(body, field, members):
    v = body.get(field)
    if not isinstance(v, str) or v not in members:
        raise errors.invalid_request("Missing or invalid enum field: %s" % field)
    return v


def optional_enum(body, field, members, default):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, str) or v not in members:
        raise errors.invalid_request("Invalid enum field: %s" % field)
    return v


def require_positive_number(body, field):
    v = body.get(field)
    if not is_number(v) or v <= 0:
        raise errors.invalid_request("Missing or non-positive numeric field: %s" % field)
    return v


def require_positive_int(body, field):
    v = body.get(field)
    if not is_int(v) or v <= 0:
        raise errors.invalid_request("Missing or non-positive integer field: %s" % field)
    return v


def require_quantity(body):
    v = body.get("quantity")
    if not is_int(v) or v < 1:
        raise errors.invalid_request("quantity must be an integer >= 1")
    return v


def require_int(body, field):
    """Required integer field; must be present and well-typed (any sign)."""
    v = body.get(field)
    if not is_int(v):
        raise errors.invalid_request("Missing or invalid integer field: %s" % field)
    return v


def require_nonneg_int(body, field):
    v = body.get(field)
    if not is_int(v) or v < 0:
        raise errors.invalid_request("Missing or negative integer field: %s" % field)
    return v


def require_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise errors.invalid_request("Missing or invalid boolean field: %s" % field)
    return v


def require_id(body, field):
    """Required FK id string; presence/type checked here (existence checked later)."""
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise errors.invalid_request("Missing or invalid id field: %s" % field)
    return v
