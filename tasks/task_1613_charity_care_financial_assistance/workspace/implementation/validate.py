"""Request-body shape validation (validation priority 13) and pagination parsing."""
from flask import request

from errors import raise_error, ERR_INVALID_REQUEST
from util import is_valid_date, is_valid_datetime


def get_body() -> dict:
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
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
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


def opt_int_or_none(body, field, minimum=None, maximum=None):
    """Integer field that may be absent or explicitly null (factor scores)."""
    if field not in body or body.get(field) is None:
        return None
    return req_int(body, field, minimum=minimum, maximum=maximum)


def req_number(body, field):
    """int or float (not bool, not string)."""
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
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
    v = req_str(body, field)
    if not is_valid_date(v):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO date: {field}")
    return v


def req_datetime(body, field):
    v = req_str(body, field)
    if not is_valid_datetime(v):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO datetime: {field}")
    return v


def req_str_list(body, field, allowed=None, non_empty=False):
    v = body.get(field)
    if not isinstance(v, list):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid list field: {field}")
    if non_empty and len(v) == 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be a non-empty list")
    for item in v:
        if not isinstance(item, str):
            raise_error(ERR_INVALID_REQUEST, f"field {field} must contain only strings")
        if allowed is not None and item not in allowed:
            raise_error(ERR_INVALID_REQUEST, f"field {field} contains value outside the declared set")
    return v


def get_pagination():
    """limit (default 10, min 1, max 100), offset (default 0) per PRD 2.3."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset
