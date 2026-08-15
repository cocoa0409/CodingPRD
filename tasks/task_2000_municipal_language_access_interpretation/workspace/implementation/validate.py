"""Request-body shape validation (priority 3, ERR_VALIDATION) and reference
resolution helpers (priority 4, per-resource not-found ids)."""
from db import db
from errors import raise_error, ERR_VALIDATION
from util import is_valid_iso_datetime


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_VALIDATION, "request body must be a JSON object")
    return body


def reject_unknown_fields(body, allowed):
    """Computed/system fields (and any non-contract key) are refused as input."""
    extra = [k for k in body.keys() if k not in allowed]
    if extra:
        raise_error(ERR_VALIDATION, f"field not accepted as input: {extra[0]}")


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_VALIDATION, f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_VALIDATION, f"invalid field type: {field}")
    return v


def opt_nullable_str(body, field, default=None):
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_error(ERR_VALIDATION, f"invalid field type: {field}")
    return v


def _check_int(v, field):
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_VALIDATION, f"missing or invalid integer field: {field}")
    return v


def req_int(body, field, positive=False, non_negative=False):
    v = _check_int(body.get(field), field)
    if positive and v <= 0:
        raise_error(ERR_VALIDATION, f"field {field} must be > 0")
    if non_negative and v < 0:
        raise_error(ERR_VALIDATION, f"field {field} must be >= 0")
    return v


def opt_int(body, field, default=None, positive=False, non_negative=False):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, positive=positive, non_negative=non_negative)


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_VALIDATION, f"missing or invalid enum field: {field}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, allowed)


def req_datetime_str(body, field):
    """Validate an ISO8601 datetime input; the original string is returned and
    stored verbatim (comparisons always re-parse)."""
    v = body.get(field)
    if not is_valid_iso_datetime(v):
        raise_error(ERR_VALIDATION, f"missing or invalid ISO8601 datetime field: {field}")
    return v


def opt_datetime_str(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_datetime_str(body, field)


def req_str_list(body, field):
    v = body.get(field)
    if not isinstance(v, list):
        raise_error(ERR_VALIDATION, f"field {field} must be an array")
    for item in v:
        if not isinstance(item, str) or item.strip() == "":
            raise_error(ERR_VALIDATION, f"field {field} must contain only non-empty strings")
    return list(v)


def opt_str_list(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_str_list(body, field)


def opt_enum_list(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, list):
        raise_error(ERR_VALIDATION, f"field {field} must be an array")
    for item in v:
        if not isinstance(item, str) or item not in allowed:
            raise_error(ERR_VALIDATION, f"field {field} contains invalid value: {item}")
    return list(v)


def require_path(collection, rid, err_spec):
    """Priority 4: path identifier existence (left to right)."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(err_spec, f"{collection} id not found: {rid}")
    return obj


def require_ref(collection, rid, err_spec, field):
    """Priority 4: body-supplied foreign key existence."""
    if rid is None:
        return None
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(err_spec, f"{field} does not resolve: {rid}")
    return obj
