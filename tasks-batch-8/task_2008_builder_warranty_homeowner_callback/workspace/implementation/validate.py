"""Request-body shape validation helpers (precedence 5) and pagination parsing."""
from errors import raise_error, ERR_INVALID_REQUEST
from util import parse_iso_date, parse_iso_datetime


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


def opt_nullable_str(body, field, default=None):
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def req_int(body, field, minimum=None, maximum=None, positive=False, non_negative=False):
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


def opt_int(body, field, default=None, minimum=None, maximum=None, positive=False, non_negative=False):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum,
                   positive=positive, non_negative=non_negative)


def req_number(body, field):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid boolean field: {field}")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid enum field: {field}")
    return v


def req_date(body, field):
    v = req_str(body, field)
    d = parse_iso_date(v)
    if d is None:
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO date: {field}")
    return d


def req_datetime(body, field):
    v = req_str(body, field)
    dt = parse_iso_datetime(v)
    if dt is None:
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO datetime: {field}")
    return dt


def pagination_params():
    """limit/offset per scaffold response_envelope pagination_defaults."""
    from flask import request
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit, offset = 10, 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def apply_page(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total
