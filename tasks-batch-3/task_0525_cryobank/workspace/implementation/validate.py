from flask import request

import errors
from errors import err


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {f}")


def require_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise err(errors.ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string")
    return v


def require_bool(data, field, default=None, required=True):
    if field not in data or data[field] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return default
    v = data[field]
    if not isinstance(v, bool):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {field} must be a boolean")
    return v


def require_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err(errors.ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(allowed)}")
    return v


def require_positive_int(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {field} must be a positive integer")
    if v < 1:
        raise err(errors.ERR_INVALID_REQUEST, f"Field {field} must be >= 1")
    return v


def require_nonneg_int(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {field} must be a non-negative integer")
    if v < 0:
        raise err(errors.ERR_INVALID_REQUEST, f"Field {field} must be >= 0")
    return v


def optional_str(data, field):
    if field not in data or data[field] is None:
        return None
    v = data[field]
    if not isinstance(v, str):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {field} must be a string")
    return v


def paginate(items):
    """Sort by creation seq ascending, apply limit/offset from query string."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            offset = 0
    ordered = sorted(items, key=lambda e: e["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
