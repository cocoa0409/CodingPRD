"""Request-body shape validation (ERR_INVALID_REQUEST) and existence helpers."""
from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from util import is_valid_datetime


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
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def _check_int(v, field):
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    return v


def req_int(body, field, minimum=None, maximum=None):
    v = _check_int(body.get(field), field)
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} above maximum {maximum}")
    return v


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum)


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
    v = req_str(body, field)
    if not is_valid_datetime(v):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO datetime: {field}")
    return v


def opt_datetime(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_datetime(body, field)


def req_obj(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, dict):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid object field: {field}")
    return v


def opt_obj(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_obj(body, field)


def req_str_list(body, field):
    v = body.get(field)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid array field: {field}")
    return list(v)


def opt_str_list(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_str_list(body, field)


def opt_bool(body, field, default=False):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"invalid boolean field: {field}")
    return v


def require_path_resource(collection, rid):
    """Existence (priority 3): path parameter must resolve to an existing entity."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"resource not found: {rid}")
    return obj


def require_body_ref(collection, rid, field):
    """Body-supplied foreign key must resolve to an existing entity."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{field} does not resolve: {rid}")
    return obj
