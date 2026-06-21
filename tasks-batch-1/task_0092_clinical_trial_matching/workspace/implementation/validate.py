"""Request-body validation helpers (PRD §2.8 priority 5 ERR_INVALID_REQUEST and
pagination parsing PRD §2.3)."""
from flask import request

from errors import err


def get_json():
    """Parse the JSON body; tolerate an empty body as {} for action endpoints."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        err("ERR_INVALID_REQUEST", "Request body must be valid JSON")
    if not isinstance(data, dict):
        err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require_fields(body, *names):
    for n in names:
        if n not in body or body[n] is None:
            err("ERR_INVALID_REQUEST", "Missing required field: %s" % n)


def is_int(v):
    # bool is a subclass of int but is not an acceptable integer payload.
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def check_int(body, name, minimum=None):
    v = body.get(name)
    if not is_int(v):
        err("ERR_INVALID_REQUEST", "Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (name, minimum))
    return v


def check_number(body, name, minimum=None):
    v = body.get(name)
    if not is_number(v):
        err("ERR_INVALID_REQUEST", "Field %s must be a number" % name)
    if minimum is not None and v < minimum:
        err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (name, minimum))
    return v


def check_string(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % name)
    return v


def check_enum(body, name, allowed):
    v = body.get(name)
    if v not in allowed:
        err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def check_action(body, name, allowed):
    """Action-discriminator validity (PRD §2.8 priority 6 -> ERR_INVALID_ACTION).

    Distinct from check_enum: an out-of-set action on /transition, /review, or
    /decide surfaces as ERR_INVALID_ACTION, not ERR_INVALID_REQUEST.
    """
    v = body.get(name)
    if v not in allowed:
        err("ERR_INVALID_ACTION", "%s must be one of %s" % (name, sorted(allowed)))
    return v


def check_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % name)
    return v


def pagination():
    """Parse limit/offset (PRD §2.3): limit default 10, min 1, max 100; offset
    default 0, min 0. Out-of-range / malformed values are clamped to bounds."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = 10
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 10
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100

    offset = 0
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            offset = 0
        if offset < 0:
            offset = 0

    return limit, offset
