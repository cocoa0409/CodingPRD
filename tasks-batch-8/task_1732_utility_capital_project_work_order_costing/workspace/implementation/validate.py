"""Request-body shape validation (priority 4) and existence checks (priority 3)."""
from datetime import date

from db import db
from errors import raise_error, ERR_VALIDATION, ERR_NOT_FOUND
from util import parse_dt, parse_date


def get_body() -> dict:
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_VALIDATION, "request body must be a JSON object")
    return body


def _fail(msg):
    raise_error(ERR_VALIDATION, msg)


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        _fail(f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, str):
        _fail(f"invalid field type: {field}")
    return v


def req_int(body, field, minimum=None, positive=False, non_negative=False):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        _fail(f"missing or invalid integer field: {field}")
    if positive and v <= 0:
        _fail(f"field {field} must be > 0")
    if non_negative and v < 0:
        _fail(f"field {field} must be >= 0")
    if minimum is not None and v < minimum:
        _fail(f"field {field} below minimum {minimum}")
    return v


def opt_int(body, field, default=None, minimum=None, positive=False, non_negative=False):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum=minimum, positive=positive, non_negative=non_negative)


def _is_number(v):
    return not isinstance(v, bool) and isinstance(v, (int, float))


def req_num(body, field, minimum=None, positive=False, non_negative=False, maximum=None):
    v = body.get(field)
    if v is None or not _is_number(v):
        _fail(f"missing or invalid numeric field: {field}")
    if positive and not v > 0:
        _fail(f"field {field} must be > 0")
    if non_negative and v < 0:
        _fail(f"field {field} must be >= 0")
    if minimum is not None and v < minimum:
        _fail(f"field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        _fail(f"field {field} above maximum {maximum}")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        _fail(f"missing or invalid enum field: {field}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, allowed)


def req_date(body, field):
    v = req_str(body, field)
    try:
        parse_date(v)
    except (ValueError, TypeError):
        _fail(f"invalid ISO date: {field}")
    return v


def opt_date(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_date(body, field)


def req_datetime(body, field):
    v = req_str(body, field)
    try:
        parse_dt(v)
    except (ValueError, TypeError):
        _fail(f"invalid ISO datetime: {field}")
    return v


def is_valid_date_str(s) -> bool:
    try:
        parse_date(s)
        return True
    except Exception:
        return False


def require_path_resource(collection, rid):
    """Priority 3: path parameter existence."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"resource not found: {rid}")
    return obj


def require_body_ref(body, field, collection):
    """Priority 3/4: a required body foreign key — presence/type is shape (400),
    existence of a presented id is ERR_NOT_FOUND (404). Existence is evaluated
    before the remaining shape checks per PRD 2.8."""
    v = body.get(field)
    if v is not None and isinstance(v, str):
        obj = db[collection].get(v)
        if obj is None:
            raise_error(ERR_NOT_FOUND, f"{field} does not resolve: {v}")
        return obj
    if v is None or not isinstance(v, str) or v.strip() == "":
        _fail(f"missing or invalid field: {field}")
    return db[collection].get(v)


def opt_body_ref(body, field, collection, default=None):
    """Optional body FK: when present and a string it must resolve (404)."""
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, str):
        _fail(f"invalid field type: {field}")
    obj = db[collection].get(v)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{field} does not resolve: {v}")
    return obj
