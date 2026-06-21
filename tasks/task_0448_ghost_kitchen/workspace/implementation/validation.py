"""Field-shape validation helpers (priority 12: ERR_INVALID_REQUEST, PRD §3.10).

These are the LAST line of defense and run after auth, ownership, existence,
idempotency, state, and the business constraints. They reject with
ERR_INVALID_REQUEST (422) on missing required fields, bad enum values, or
numeric/ordering constraint violations.
"""
import errors


def get_body():
    """Return the JSON body as a dict, or {} when none/empty/non-object."""
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise errors.invalid_request("Missing required field: %s" % field)
    return body[field]


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request("Field %s must be a non-empty string." % field)
    return val


def require_int(body, field):
    val = require(body, field)
    # bool is a subclass of int; reject it explicitly.
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field %s must be an integer." % field)
    return val


def require_enum(body, field, allowed):
    val = require(body, field)
    if val not in allowed:
        raise errors.invalid_request(
            "Field %s must be one of %s." % (field, sorted(allowed)))
    return val


def optional_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field %s must be an integer." % field)
    return val
