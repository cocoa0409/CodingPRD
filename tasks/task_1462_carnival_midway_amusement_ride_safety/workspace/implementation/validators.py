"""Request-body shape validation helpers (validation family 5: ERR_INVALID_REQUEST)."""
from datetime import datetime

from errors import raise_err, ERR_INVALID_REQUEST
from flask import request


def get_body():
    """Parse the JSON request body. No body -> {}; malformed/non-object -> 400."""
    data = request.get_json(silent=True)
    if data is None:
        if request.data and request.data.strip():
            raise_err(ERR_INVALID_REQUEST, "Request body is not valid JSON")
        return {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def reject_unknown(body, allowed):
    extra = [k for k in body.keys() if k not in allowed]
    if extra:
        raise_err(ERR_INVALID_REQUEST, "Unknown or computed field(s): %s" % ", ".join(sorted(extra)))


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, name, allow_blank=False):
    if name not in body:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: %s" % name)
    v = body[name]
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, "Field %s must be a string" % name)
    if not allow_blank and v.strip() == "":
        raise_err(ERR_INVALID_REQUEST, "Field %s must be non-blank" % name)
    return v


def opt_str(body, name):
    if name not in body or body[name] is None:
        return None
    v = body[name]
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, "Field %s must be a string" % name)
    return v


def req_int(body, name, lo=None, hi=None):
    if name not in body:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: %s" % name)
    v = body[name]
    if not _is_int(v):
        raise_err(ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    if lo is not None and v < lo:
        raise_err(ERR_INVALID_REQUEST, "Field %s is below its minimum" % name)
    if hi is not None and v > hi:
        raise_err(ERR_INVALID_REQUEST, "Field %s is above its maximum" % name)
    return v


def req_enum(body, name, allowed):
    if name not in body:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: %s" % name)
    v = body[name]
    if not isinstance(v, str) or v not in allowed:
        raise_err(ERR_INVALID_REQUEST, "Field %s must be one of %s" % (name, ", ".join(allowed)))
    return v


def req_date(body, name):
    """Strict YYYY-MM-DD date; returns a datetime.date."""
    if name not in body:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: %s" % name)
    v = body[name]
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, "Field %s must be an ISO date string" % name)
    try:
        if len(v) != 10:
            raise ValueError
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "Field %s must be a valid YYYY-MM-DD date" % name)


def req_str_list(body, name, allowed):
    if name not in body:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: %s" % name)
    v = body[name]
    if not isinstance(v, list) or len(v) == 0:
        raise_err(ERR_INVALID_REQUEST, "Field %s must be a non-empty array" % name)
    for item in v:
        if not isinstance(item, str) or item not in allowed:
            raise_err(ERR_INVALID_REQUEST, "Field %s contains an invalid entry" % name)
    return v
