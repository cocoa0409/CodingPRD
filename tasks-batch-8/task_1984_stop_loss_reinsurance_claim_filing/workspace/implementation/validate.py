"""Request-body shape validation (ERR_INVALID_REQUEST) and reference resolution
(ERR_NOT_FOUND for both path identifiers and body foreign keys — PRD §2.9)."""
from datetime import datetime, date

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND


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


def req_number(body, field):
    """A JSON number (int or float; booleans rejected)."""
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid enum field: {field}")
    return v


def req_datetime(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or not v.strip():
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid datetime field: {field}")
    _check_datetime(v, field)
    return v


def opt_datetime(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_datetime(body, field)


def _check_datetime(v, field):
    s = v.strip()
    try:
        if s.endswith("Z"):
            datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO 8601 datetime: {field}")


def req_date(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or not v.strip():
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid date field: {field}")
    try:
        date.fromisoformat(v.strip())
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO date (YYYY-MM-DD): {field}")
    return v


def req_str_list(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, list):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid array field: {field}")
    for item in v:
        if not isinstance(item, str):
            raise_error(ERR_INVALID_REQUEST, f"field {field} must contain only strings")
    return list(v)


def require_path_resource(collection, rid):
    """Priority 3: path parameter existence (left-to-right resolution)."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{collection} id not found: {rid}")
    return obj


def require_ref(collection, rid, field):
    """Priority 3: body-supplied foreign key existence."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{field} does not resolve: {rid}")
    return obj
