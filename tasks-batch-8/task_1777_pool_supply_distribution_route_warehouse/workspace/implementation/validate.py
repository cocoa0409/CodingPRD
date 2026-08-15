"""Request-body shape validation and reference existence helpers."""
import re
from datetime import date, datetime

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND


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
    """A string field that may legitimately be set to null (PATCH semantics)."""
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
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be <= {maximum}")
    return v


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum)


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid boolean field: {field}")
    return v


def opt_bool(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_bool(body, field)


def req_number(body, field, minimum=None, maximum=None):
    """A JSON number (int or float, not bool)."""
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be <= {maximum}")
    return v


def opt_number(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return req_number(body, field, minimum=minimum, maximum=maximum)


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid enum field: {field}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, allowed)


def _validate_date_str(v, field):
    try:
        date.fromisoformat(v.strip())
    except (ValueError, TypeError, AttributeError):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO date: {field}")


def _validate_datetime_str(v, field):
    s = v.strip()
    try:
        if s.endswith("Z"):
            datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            datetime.fromisoformat(s)
    except (ValueError, TypeError, AttributeError):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO datetime: {field}")


def req_date(body, field):
    v = req_str(body, field)
    _validate_date_str(v, field)
    return v


def opt_date(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_date(body, field)


def opt_nullable_date(body, field, default=None):
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    _validate_date_str(v, field)
    return v


def req_datetime(body, field):
    v = req_str(body, field)
    _validate_datetime_str(v, field)
    return v


def opt_datetime(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_datetime(body, field)


_MM_DD = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


def req_mmdd(body, field):
    v = req_str(body, field)
    if not _MM_DD.match(v.strip()):
        raise_error(ERR_INVALID_REQUEST, f"invalid MM-DD value: {field}")
    return v.strip()


def require_path_resource(collection, rid):
    """Priority 4: path parameter existence -> ERR_RESOURCE_NOT_FOUND."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_RESOURCE_NOT_FOUND, f"{collection} id not found: {rid}")
    return obj


def require_ref(collection, rid, field):
    """Priority 4: body-supplied foreign key existence -> ERR_RESOURCE_NOT_FOUND."""
    if rid is None:
        return None
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_RESOURCE_NOT_FOUND, f"{field} does not resolve: {rid}")
    return obj
