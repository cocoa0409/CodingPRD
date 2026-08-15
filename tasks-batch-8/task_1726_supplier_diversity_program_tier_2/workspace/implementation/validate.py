"""Request-body schema helpers and resource resolution (validation ladder)."""
from decimal import Decimal, InvalidOperation

from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from util import parse_clock_input, parse_date


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
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


def req_date(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid date field: {field}")
    d = parse_date(v)
    if d is None:
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO date (YYYY-MM-DD): {field}")
    return d


def req_decimal(body, field):
    """Required JSON number (int or float, not bool) or numeric string; Decimal."""
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise_error(ERR_INVALID_REQUEST, f"invalid numeric field: {field}")
    if d.is_nan() or d.is_infinite():
        raise_error(ERR_INVALID_REQUEST, f"invalid numeric field: {field}")
    return d


def req_clock_instant(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid datetime field: {field}")
    dt = parse_clock_input(v)
    if dt is None:
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO 8601 timestamp: {field}")
    return dt


def get_resource(collection, rid):
    rec = db[collection].get(rid)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"{collection} resource not found: {rid}")
    return rec
