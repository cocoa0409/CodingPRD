"""Request-body shape validation (priority 14) and existence helpers (priority 4)."""
from db import db
from errors import raise_error, ERR_VALIDATION, ERR_NOT_FOUND
from util import is_valid_date, is_valid_period, dec, decimal_places


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_VALIDATION, "request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_VALIDATION, f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise_error(ERR_VALIDATION, f"invalid field type: {field}")
    return v


def req_int(body, field, minimum=None, maximum=None, positive=False, non_negative=False):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_VALIDATION, f"missing or invalid integer field: {field}")
    if positive and v <= 0:
        raise_error(ERR_VALIDATION, f"field {field} must be > 0")
    if non_negative and v < 0:
        raise_error(ERR_VALIDATION, f"field {field} must be >= 0")
    if minimum is not None and v < minimum:
        raise_error(ERR_VALIDATION, f"field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise_error(ERR_VALIDATION, f"field {field} above maximum {maximum}")
    return v


def opt_int(body, field, default=None, minimum=None, maximum=None, positive=False, non_negative=False):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum,
                   positive=positive, non_negative=non_negative)


def req_number(body, field):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_VALIDATION, f"missing or invalid numeric field: {field}")
    return v


def opt_number(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_number(body, field)


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_VALIDATION, f"missing or invalid enum field: {field}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, allowed)


def req_date(body, field):
    v = body.get(field)
    if not is_valid_date(v):
        raise_error(ERR_VALIDATION, f"missing or invalid ISO date: {field}")
    return v


def opt_date(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_date(body, field)


def req_period(body, field):
    v = body.get(field)
    if not is_valid_period(v):
        raise_error(ERR_VALIDATION, f"missing or invalid period (YYYY-MM): {field}")
    return v


def req_score(body_value, field):
    """A 0-100 measure score/threshold (number)."""
    v = body_value
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_VALIDATION, f"missing or invalid score field: {field}")
    if dec(v) < 0 or dec(v) > 100:
        raise_error(ERR_VALIDATION, f"field {field} must be within 0-100")
    return v


def require_path_resource(collection, rid):
    """Priority 4: path parameter existence."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{collection} id not found: {rid}")
    return obj


def require_body_ref(collection, value, field):
    """Priority 4: body FK existence (only when the field is present and a string;
    shape problems are reported later as ERR_VALIDATION)."""
    if value is None or not isinstance(value, str):
        return None
    obj = db[collection].get(value)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{field} does not resolve: {value}")
    return obj
