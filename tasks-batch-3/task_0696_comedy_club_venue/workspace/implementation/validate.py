"""Request-shape validation helpers (priority-5 ERR_INVALID_REQUEST,
and pagination ERR_INVALID_PAGINATION)."""
from flask import request

import errors
from errors import ApiError


def body():
    """Parsed JSON body as a dict (empty dict when absent)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Request body must be a JSON object")
    return data


def require(data, field):
    if field not in data or data[field] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Missing required field: %s" % field)
    return data[field]


def require_str(data, field):
    v = require(data, field)
    if not isinstance(v, str) or v == "":
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Field %s must be a non-empty string" % field)
    return v


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Field %s must be a string" % field)
    return v


def require_int(data, field, minimum=None):
    v = require(data, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Field %s must be >= %s" % (field, minimum))
    return v


def opt_int(data, field, default=None, minimum=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Field %s must be >= %s" % (field, minimum))
    return v


def opt_bool(data, field, default=False):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, bool):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Field %s must be a boolean" % field)
    return v


def require_pct(data, field):
    v = require(data, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Field %s must be a number" % field)
    if v < 0 or v > 1:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Field %s must be in [0,1]" % field)
    return v


def opt_pct(data, field, default):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Field %s must be a number" % field)
    if v < 0 or v > 1:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Field %s must be in [0,1]" % field)
    return v


def require_enum(data, field, allowed):
    v = require(data, field)
    if v not in allowed:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def require_iso(data, field):
    import clock
    v = require_str(data, field)
    try:
        clock.parse_iso8601(v)
    except Exception:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Field %s must be an ISO 8601 instant" % field)
    return v


def pagination():
    """Parse limit/offset query params (PRD §2.3). limit in [1,100] default 10;
    offset >= 0 default 0. Out of range -> ERR_INVALID_PAGINATION (422)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError(errors.ERR_INVALID_PAGINATION, 422, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(errors.ERR_INVALID_PAGINATION, 422, "limit must be in [1,100]")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError(errors.ERR_INVALID_PAGINATION, 422, "offset must be an integer")
        if offset < 0:
            raise ApiError(errors.ERR_INVALID_PAGINATION, 422, "offset must be >= 0")
    return limit, offset
