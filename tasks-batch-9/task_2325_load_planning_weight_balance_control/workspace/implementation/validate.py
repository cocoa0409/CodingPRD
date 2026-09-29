"""Request-shape validation (priority 3) and pagination (PRD §2.3)."""
from flask import request

import db
from errors import ERR_INVALID_REQUEST, fail

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        fail(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return payload


def _present(payload, name):
    return name in payload and payload[name] is not None


def req_str(payload, name):
    if not _present(payload, name):
        fail(ERR_INVALID_REQUEST, "Field '%s' is required." % name)
    value = payload[name]
    if not isinstance(value, str) or not value.strip():
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a non-empty string." % name)
    return value


def opt_str(payload, name, default=None):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a string." % name)
    return value


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a number." % name)
    return value


def req_num(payload, name, ge=None, gt=None):
    if not _present(payload, name):
        fail(ERR_INVALID_REQUEST, "Field '%s' is required." % name)
    return _check_bounds(_number(payload[name], name), name, ge, gt)


def opt_num(payload, name, default=None, ge=None, gt=None):
    if not _present(payload, name):
        return default
    return _check_bounds(_number(payload[name], name), name, ge, gt)


def _check_bounds(value, name, ge, gt):
    if ge is not None and value < ge:
        fail(ERR_INVALID_REQUEST, "Field '%s' must be >= %s." % (name, ge))
    if gt is not None and value <= gt:
        fail(ERR_INVALID_REQUEST, "Field '%s' must be > %s." % (name, gt))
    return value


def _integer(value, name):
    if isinstance(value, bool):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be an integer." % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    fail(ERR_INVALID_REQUEST, "Field '%s' must be an integer." % name)


def req_int(payload, name, ge=None):
    if not _present(payload, name):
        fail(ERR_INVALID_REQUEST, "Field '%s' is required." % name)
    return _check_bounds(_integer(payload[name], name), name, ge, None)


def opt_int(payload, name, default=None, ge=None):
    if not _present(payload, name):
        return default
    return _check_bounds(_integer(payload[name], name), name, ge, None)


def req_enum(payload, name, allowed):
    value = req_str(payload, name)
    if value not in allowed:
        fail(ERR_INVALID_REQUEST, "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(payload, name, allowed, default=None):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        fail(ERR_INVALID_REQUEST, "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_bool(payload, name, default=False):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, bool):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a boolean." % name)
    return value


def has(payload, name):
    return _present(payload, name)


# ------------------------------------------------------------------ filters
def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        fail(ERR_INVALID_REQUEST, "Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail(ERR_INVALID_REQUEST, "Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            fail(ERR_INVALID_REQUEST, "Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail(ERR_INVALID_REQUEST, "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail(ERR_INVALID_REQUEST, "Query parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(rows):
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return [db.public(r) for r in window], meta
