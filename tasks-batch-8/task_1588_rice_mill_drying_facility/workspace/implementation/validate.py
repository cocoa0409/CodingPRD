"""Request-body shape validation (priority 4) helpers."""
from datetime import date, datetime
from decimal import Decimal

from errors import raise_error, ERR_INVALID_REQUEST
from util import D


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def _present(body, field):
    return field in body and body.get(field) is not None


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    if not _present(body, field):
        return default
    v = body.get(field)
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def req_int(body, field, non_negative=False, positive=False):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    if positive and v <= 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be > 0")
    if non_negative and v < 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be >= 0")
    return v


def opt_int(body, field, default=None, non_negative=False, positive=False):
    if not _present(body, field):
        return default
    return req_int(body, field, non_negative=non_negative, positive=positive)


def _is_num(v):
    return not isinstance(v, bool) and isinstance(v, (int, float))


def req_num(body, field, positive=False, non_negative=False) -> Decimal:
    v = body.get(field)
    if v is None or not _is_num(v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    d = D(v)
    if positive and d <= 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be > 0")
    if non_negative and d < 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be >= 0")
    return d


def opt_num(body, field, default=None, positive=False, non_negative=False):
    if not _present(body, field):
        return default
    return req_num(body, field, positive=positive, non_negative=non_negative)


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid enum field: {field}")
    return v


def req_date(body, field):
    v = req_str(body, field)
    try:
        date.fromisoformat(v.strip())
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO date: {field}")
    return v.strip()


def req_datetime(body, field):
    v = req_str(body, field)
    _check_datetime(v, field)
    return v.strip()


def _check_datetime(v, field):
    s = v.strip()
    try:
        if s.endswith("Z"):
            datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO datetime: {field}")


def req_str_list(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, list):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid array field: {field}")
    for item in v:
        if not isinstance(item, str):
            raise_error(ERR_INVALID_REQUEST, f"field {field} must contain only strings")
    return list(v)


def req_grade_adjustments(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, dict):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid object field: {field}")
    from services.core import GRADES
    out = {}
    for k, val in v.items():
        if k not in GRADES:
            raise_error(ERR_INVALID_REQUEST, f"invalid grade key in {field}: {k}")
        if val is None or isinstance(val, bool) or not isinstance(val, int):
            raise_error(ERR_INVALID_REQUEST, f"grade adjustment for {k} must be integer cents")
        out[k] = val
    return out


def opt_grade_adjustments(body, field, default=None):
    if not _present(body, field):
        return default
    return req_grade_adjustments(body, field)
