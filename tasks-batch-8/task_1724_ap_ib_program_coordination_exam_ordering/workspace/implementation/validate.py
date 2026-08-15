"""Request-body shape validation (priority 4) and reference checks (priorities 3/5)."""
from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND
from util import parse_dt


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def reject_unknown_fields(body, allowed):
    for key in body:
        if key not in allowed:
            raise_error(ERR_INVALID_REQUEST, f"unexpected field in payload: {key}")


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid field: {field}")
    return v


def req_str_allow_empty(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid field: {field}")
    return v


def req_int(body, field, minimum=None, maximum=None, positive=False, non_negative=False):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
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


def opt_int(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field)


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


def req_datetime(body, field):
    """Returns the parsed datetime (UTC, second precision)."""
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid datetime field: {field}")
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO 8601 datetime: {field}")


def require_path_resource(collection, rid):
    """Priority 3: path parameter existence."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{collection} id not found: {rid}")
    return obj


def require_ref(collection, rid, field):
    """Priority 5: body-supplied foreign key existence."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_REFERENCE_NOT_FOUND, f"{field} does not resolve: {rid}")
    return obj
