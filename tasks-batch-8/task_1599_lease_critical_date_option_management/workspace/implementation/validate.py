"""Request-body shape validation (ERR_VALIDATION / 400) and typed field readers."""
from flask import request

from errors import raise_error, ERR_VALIDATION
from util import is_valid_dateish, parse_date_value


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error(ERR_VALIDATION, "request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_VALIDATION, f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, str):
        raise_error(ERR_VALIDATION, f"invalid field type: {field}")
    return v


def req_int(body, field, positive=False, non_negative=False, minimum=None, maximum=None):
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


def opt_int(body, field, default=None, positive=False, non_negative=False, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, positive=positive, non_negative=non_negative,
                   minimum=minimum, maximum=maximum)


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_VALIDATION, f"missing or invalid enum field: {field}")
    return v


def opt_bool(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, bool):
        raise_error(ERR_VALIDATION, f"invalid boolean field: {field}")
    return v


def req_dateish(body, field):
    """Required calendar field: YYYY-MM-DD or ISO datetime; returned as a date."""
    v = body.get(field)
    if v is None or not isinstance(v, str) or not is_valid_dateish(v):
        raise_error(ERR_VALIDATION, f"missing or invalid date/datetime field: {field}")
    return parse_date_value(v)


def opt_dateish(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_dateish(body, field)


def opt_nullable_str(body, field, default=None):
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_error(ERR_VALIDATION, f"invalid field type: {field}")
    return v
