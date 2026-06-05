from flask import request
from errors import err, ERR_INVALID_REQUEST, ERR_VALIDATION_RANGE


def get_json():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    return body[field]


def req_str(body, field, allow_empty=False):
    v = require(body, field)
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a string" % field)
    if not allow_empty and v.strip() == "":
        raise err(ERR_INVALID_REQUEST, "Field %s must be non-empty" % field)
    return v


def req_int(body, field):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    return v


def opt_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    return v


def req_number(body, field):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a number" % field)
    return v


def opt_number(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a number" % field)
    return v


def opt_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a boolean" % field)
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        raise err(ERR_INVALID_REQUEST, "Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def zip5(body, field):
    v = req_str(body, field)
    if len(v) != 5 or not v.isdigit():
        raise err(ERR_INVALID_REQUEST, "Field %s must be a 5-digit ZIP" % field)
    return v


def pagination():
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset
