"""Body parsing, field validators, and pagination parsing (priority 8a shape checks)."""
from flask import request

from errors import raise_error, ERR_INVALID_REQUEST


def is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def body_dict() -> dict:
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def req_str(body, field, nonempty=True):
    v = body.get(field)
    if not isinstance(v, str) or (nonempty and not v.strip()):
        raise_error(ERR_INVALID_REQUEST, f"field '{field}' is required and must be a non-empty string")
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"field '{field}' must be a string")
    return v


def req_int(body, field, minv=None, maxv=None):
    v = body.get(field)
    if not is_int(v):
        raise_error(ERR_INVALID_REQUEST, f"field '{field}' is required and must be an integer")
    if minv is not None and v < minv:
        raise_error(ERR_INVALID_REQUEST, f"field '{field}' must be >= {minv}")
    if maxv is not None and v > maxv:
        raise_error(ERR_INVALID_REQUEST, f"field '{field}' must be <= {maxv}")
    return v


def opt_int(body, field, minv=None, maxv=None):
    v = body.get(field)
    if v is None:
        return None
    if not is_int(v):
        raise_error(ERR_INVALID_REQUEST, f"field '{field}' must be an integer")
    if minv is not None and v < minv:
        raise_error(ERR_INVALID_REQUEST, f"field '{field}' must be >= {minv}")
    if maxv is not None and v > maxv:
        raise_error(ERR_INVALID_REQUEST, f"field '{field}' must be <= {maxv}")
    return v


def req_enum(body, field, values):
    v = body.get(field)
    if not isinstance(v, str) or v not in values:
        raise_error(ERR_INVALID_REQUEST, f"field '{field}' must be one of {sorted(values)}")
    return v


def opt_enum(body, field, values):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or v not in values:
        raise_error(ERR_INVALID_REQUEST, f"field '{field}' must be one of {sorted(values)}")
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"field '{field}' is required and must be a boolean")
    return v


def req_list(body, field):
    v = body.get(field)
    if not isinstance(v, list):
        raise_error(ERR_INVALID_REQUEST, f"field '{field}' is required and must be an array")
    return v


def opt_list(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, list):
        raise_error(ERR_INVALID_REQUEST, f"field '{field}' must be an array")
    return v


def pagination_params():
    """limit: default 10, min 1, max 100; offset: default 0, min 0 (PRD 2.3)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit.strip())
        except (ValueError, AttributeError):
            raise_error(ERR_INVALID_REQUEST, "query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "query parameter 'limit' must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset.strip())
        except (ValueError, AttributeError):
            raise_error(ERR_INVALID_REQUEST, "query parameter 'offset' must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "query parameter 'offset' must be >= 0")
    return limit, offset
