"""Request-body shape validation helpers (priority 3.7) and FK existence (priority 3)."""
from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from util import is_valid_date, is_valid_datetime


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def opt_nullable_str(body, field, default=None):
    """A string field that may legitimately be set to null."""
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if v is None or not _is_int(v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} above maximum {maximum}")
    return v


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and v == v and v not in (float("inf"), float("-inf")))


def req_num(body, field):
    v = body.get(field)
    if v is None or not _is_num(v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    return v


def opt_num(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_num(body, field)


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


def req_date(body, field):
    v = body.get(field)
    if not is_valid_date(v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid ISO date: {field}")
    return v.strip()


def opt_date(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_date(body, field)


def req_datetime(body, field):
    v = body.get(field)
    if not is_valid_datetime(v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid ISO datetime: {field}")
    return v.strip()


def req_enum_list(body, field, allowed, non_empty=True):
    v = body.get(field)
    if not isinstance(v, list) or (non_empty and len(v) == 0):
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be a non-empty array")
    for item in v:
        if not isinstance(item, str) or item not in allowed:
            raise_error(ERR_INVALID_REQUEST, f"field {field} contains invalid value: {item}")
    return list(v)


def require_path_resource(collection, rid):
    """Priority 3: path parameter existence."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{collection} id not found: {rid}")
    return obj


def require_fk(collection, rid, field):
    """Priority 3: request-body foreign-key existence (ERR_NOT_FOUND)."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{field} does not reference an existing resource: {rid}")
    return obj


def opt_fk(collection, rid, field):
    if rid is None:
        return None
    return require_fk(collection, rid, field)
