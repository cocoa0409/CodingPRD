"""Request-body shape validation (tier 5) and existence helpers (tier 4)."""
from decimal import Decimal

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from util import dec, parse_dt


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def is_number(v) -> bool:
    return not isinstance(v, bool) and isinstance(v, (int, float))


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


def req_int(body, field, positive=False, non_negative=False, minimum=None, maximum=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    if positive and v <= 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be > 0")
    if non_negative and v < 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be >= 0")
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} above maximum {maximum}")
    return v


def opt_int(body, field, default=None, positive=False, non_negative=False,
            minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, positive=positive, non_negative=non_negative,
                   minimum=minimum, maximum=maximum)


def req_num(body, field, positive=False, non_negative=False) -> Decimal:
    v = body.get(field)
    if v is None or not is_number(v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    d = dec(v)
    if positive and d <= 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be > 0")
    if non_negative and d < 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be >= 0")
    return d


def opt_num(body, field, default=None, positive=False, non_negative=False):
    if field not in body or body.get(field) is None:
        return default
    return req_num(body, field, positive=positive, non_negative=non_negative)


def req_pct(body, field) -> Decimal:
    """Percentage field within 0..100 (tier 5)."""
    d = req_num(body, field)
    if d < 0 or d > 100:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be within 0..100")
    return d


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid enum field: {field}")
    return v


def req_datetime(body, field) -> str:
    """Validate and return the canonical (whole-second UTC) form."""
    v = body.get(field)
    if v is None or not isinstance(v, str) or not v.strip():
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid datetime field: {field}")
    try:
        from util import canon
        return canon(parse_dt(v))
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO 8601 datetime: {field}")


def opt_datetime(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_datetime(body, field)


def require_path_resource(collection, rid):
    """Tier 4: path parameter existence (validated left to right by callers)."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{collection} id not found: {rid}")
    return obj


def check_body_fk(collection, value, field):
    """Tier 4: body-supplied FK existence.

    Evaluated before full shape validation per the tier order (existence 4
    precedes request shape 5). Only string values can dangle; missing or
    non-string values are left for the tier-5 shape check to report.
    """
    if value is None or not isinstance(value, str):
        return None
    obj = db[collection].get(value)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{field} does not resolve: {value}")
    return obj
