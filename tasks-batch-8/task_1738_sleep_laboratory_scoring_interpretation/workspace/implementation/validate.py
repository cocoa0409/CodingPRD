"""Request-body shape validation (priority 4) and referenced-resource existence (priority 3)."""
from datetime import date, datetime

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND


def get_body() -> dict:
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def _is_str(v):
    return isinstance(v, str)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(body, field):
    v = body.get(field)
    if v is None or not _is_str(v) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not _is_str(v):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def req_int(body, field, minimum=None, maximum=None, positive=False, non_negative=False):
    v = body.get(field)
    if v is None or not _is_int(v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    if positive and v <= 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be > 0")
    if non_negative and v < 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be >= 0")
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} above maximum {maximum}")
    return v


def opt_int(body, field, default=None, minimum=None, maximum=None, positive=False, non_negative=False):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum,
                   positive=positive, non_negative=non_negative)


def req_num(body, field):
    v = body.get(field)
    if v is None or not _is_num(v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    return v


def opt_num(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not _is_num(v):
        raise_error(ERR_INVALID_REQUEST, f"invalid numeric field: {field}")
    return v


def req_bool(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid boolean field: {field}")
    return v


def opt_bool(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"invalid boolean field: {field}")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid enum field: {field}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, allowed)


def _valid_date(v) -> bool:
    try:
        date.fromisoformat(v)
        return True
    except (ValueError, TypeError):
        return False


def req_date(body, field):
    v = req_str(body, field)
    if not _valid_date(v):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO date: {field}")
    return v


def req_datetime_str(body, field):
    v = req_str(body, field)
    s = v.strip()
    try:
        if s.endswith("Z"):
            datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO datetime: {field}")
    return v


def require_path_resource(collection, rid):
    """Priority 3: path-parameter existence."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{collection} id not found: {rid}")
    return obj


def require_body_ref(collection, rid):
    """Priority 3: body foreign-key existence (only when the id is present)."""
    if rid is None:
        return None
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{collection} id not found: {rid}")
    return obj
