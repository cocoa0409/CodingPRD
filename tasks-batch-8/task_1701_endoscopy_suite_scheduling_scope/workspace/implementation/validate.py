"""Request-body schema helpers (ladder rung 4) and reference resolution (rung 3)."""
from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from util import parse_instant, parse_date


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
    if field not in body:
        return default
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


def req_bool(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid boolean field: {field}")
    return v


def opt_bool(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_bool(body, field)


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
    """Required ISO 8601 datetime; returns the aware datetime."""
    v = body.get(field)
    if v is None or not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid datetime field: {field}")
    dt = parse_instant(v)
    if dt is None:
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO datetime: {field}")
    return dt


def opt_datetime(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_datetime(body, field)


def req_date(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid date field: {field}")
    d = parse_date(v)
    if d is None:
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO date (YYYY-MM-DD): {field}")
    return d


def req_number(body, field):
    """Required JSON number (int or float, not bool)."""
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    return v


def require_path_resource(collection, rid, error_spec):
    """Rung 3: path-parameter existence with its dedicated 404 id."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(error_spec, f"{collection} id not found: {rid}")
    return obj


def resolve_ref(collection, value, error_spec):
    """Rung 3: body-supplied FK. A present-but-unresolvable reference 404s.

    Returns None when the value is absent/None (schema validation reports the
    missing required field at rung 4, after existence).
    """
    if value is None:
        return None
    obj = db[collection].get(value) if isinstance(value, str) else None
    if obj is None:
        raise_error(error_spec, f"reference does not resolve: {value}")
    return obj
