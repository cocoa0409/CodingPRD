"""Request-body field validators. All failures raise ERR_VALIDATION (400)."""
from flask import request

from errors import ApiError, ERR_VALIDATION
from util import D, parse_date, parse_datetime


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, 400, "request body must be a JSON object")
    return data


def _fail(field, msg):
    raise ApiError(ERR_VALIDATION, 400, f"'{field}': {msg}")


def present(body, field):
    return field in body and body[field] is not None


def req_str(body, field):
    if not present(body, field):
        _fail(field, "is required")
    v = body[field]
    if not isinstance(v, str) or v == "":
        _fail(field, "must be a non-empty string")
    return v


def opt_str(body, field):
    if not present(body, field):
        return None
    v = body[field]
    if not isinstance(v, str):
        _fail(field, "must be a string")
    return v


def _bounds(v, field, gt, ge, lt, le):
    if gt is not None and not v > D(gt):
        _fail(field, f"must be > {gt}")
    if ge is not None and not v >= D(ge):
        _fail(field, f"must be >= {ge}")
    if lt is not None and not v < D(lt):
        _fail(field, f"must be < {lt}")
    if le is not None and not v <= D(le):
        _fail(field, f"must be <= {le}")


def req_int(body, field, gt=None, ge=None, lt=None, le=None):
    if not present(body, field):
        _fail(field, "is required")
    v = body[field]
    if not isinstance(v, int) or isinstance(v, bool):
        _fail(field, "must be an integer")
    _bounds(v, field, gt, ge, lt, le)
    return v


def req_num(body, field, gt=None, ge=None, lt=None, le=None):
    """Returns (raw_value, Decimal)."""
    if not present(body, field):
        _fail(field, "is required")
    v = body[field]
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        _fail(field, "must be a number")
    d = D(v)
    _bounds(d, field, gt, ge, lt, le)
    return v, d


def opt_num(body, field, gt=None, ge=None, lt=None, le=None):
    if not present(body, field):
        return None, None
    return req_num(body, field, gt=gt, ge=ge, lt=lt, le=le)


def req_bool(body, field):
    if not present(body, field):
        _fail(field, "is required")
    if not isinstance(body[field], bool):
        _fail(field, "must be a boolean")
    return body[field]


def req_enum(body, field, values):
    if not present(body, field):
        _fail(field, "is required")
    v = body[field]
    if not isinstance(v, str) or v not in values:
        _fail(field, f"must be one of {sorted(values)}")
    return v


def req_date(body, field):
    """Returns datetime.date; the wire value echoes as date.isoformat()."""
    if not present(body, field):
        _fail(field, "is required")
    try:
        return parse_date(body[field])
    except ValueError:
        _fail(field, "must be a valid YYYY-MM-DD date")


def req_datetime(body, field):
    if not present(body, field):
        _fail(field, "is required")
    try:
        return parse_datetime(body[field])
    except (ValueError, TypeError):
        _fail(field, "must be a valid ISO8601 timestamp")


def pagination():
    """limit/offset query params per PRD 2.3: limit default 10 in [1,100], offset default 0 >= 0."""
    limit, offset = 10, 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise ApiError(ERR_VALIDATION, 400, "'limit': must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_VALIDATION, 400, "'limit': must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise ApiError(ERR_VALIDATION, 400, "'offset': must be an integer")
        if offset < 0:
            raise ApiError(ERR_VALIDATION, 400, "'offset': must be >= 0")
    return limit, offset
