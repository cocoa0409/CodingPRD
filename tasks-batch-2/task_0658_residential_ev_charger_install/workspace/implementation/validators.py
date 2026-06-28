"""Request-body parsing & shape validation helpers.

These raise ERR_INVALID_REQUEST (400) for missing/wrong-type/bad-enum fields and
ERR_VALIDATION_LIMIT (422) for numeric inputs out of declared bounds. The caller
decides ordering relative to other checks; per PRD §3.10 the generic request-shape
validation (ERR_INVALID_REQUEST) is the LAST check, but auth/existence/etc. run
first and are handled outside here. Field-level shape checks that must precede
domain logic (e.g. parsing FK ids) are deferred until after auth/existence in each
route; bound checks (ERR_VALIDATION_LIMIT) are explicit per the error catalog.
"""
import errors
from errors import err


def get_body():
    from flask import request
    if request.data and len(request.data) > 0:
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            body = None
        if body is None:
            raise err(errors.ERR_INVALID_REQUEST, "malformed JSON body")
        if not isinstance(body, dict):
            raise err(errors.ERR_INVALID_REQUEST, "body must be an object")
        return body
    return {}


def require_str(body, field):
    if field not in body or body[field] is None:
        raise err(errors.ERR_INVALID_REQUEST, f"missing required field: {field}")
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise err(errors.ERR_INVALID_REQUEST, f"field {field} must be a non-empty string")
    return val


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err(errors.ERR_INVALID_REQUEST, f"field {field} must be a string")
    return val


def require_int(body, field):
    if field not in body or body[field] is None:
        raise err(errors.ERR_INVALID_REQUEST, f"missing required field: {field}")
    val = body[field]
    # bool is a subclass of int; reject it as a non-int.
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(errors.ERR_INVALID_REQUEST, f"field {field} must be an integer")
    return val


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(errors.ERR_INVALID_REQUEST, f"field {field} must be an integer")
    return val


def require_bool(body, field):
    if field not in body or body[field] is None:
        raise err(errors.ERR_INVALID_REQUEST, f"missing required field: {field}")
    val = body[field]
    if not isinstance(val, bool):
        raise err(errors.ERR_INVALID_REQUEST, f"field {field} must be a boolean")
    return val


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err(errors.ERR_INVALID_REQUEST, f"field {field} must be a boolean")
    return val


def require_enum(body, field, allowed):
    val = require_str(body, field)
    if val not in allowed:
        raise err(errors.ERR_INVALID_REQUEST, f"field {field} must be one of {sorted(allowed)}")
    return val


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in allowed:
        raise err(errors.ERR_INVALID_REQUEST, f"field {field} must be one of {sorted(allowed)}")
    return val


def require_int_array(body, field, non_negative=True):
    if field not in body or body[field] is None:
        raise err(errors.ERR_INVALID_REQUEST, f"missing required field: {field}")
    val = body[field]
    if not isinstance(val, list):
        raise err(errors.ERR_INVALID_REQUEST, f"field {field} must be an array")
    out = []
    for item in val:
        if isinstance(item, bool) or not isinstance(item, int):
            raise err(errors.ERR_INVALID_REQUEST, f"field {field} must contain integers")
        if non_negative and item < 0:
            raise err(errors.ERR_INVALID_REQUEST, f"field {field} entries must be non-negative")
        out.append(item)
    return out
