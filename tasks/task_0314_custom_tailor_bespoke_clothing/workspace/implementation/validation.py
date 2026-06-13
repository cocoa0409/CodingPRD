"""Request-body field validation helpers (ERR_INVALID_REQUEST / 400) and
pagination parsing (PRD §2.3)."""
from flask import request

import errors
from errors import fail

_MISSING = object()


def require(body, key):
    if key not in body or body[key] is None:
        fail(errors.ERR_INVALID_REQUEST, f"Missing required field: {key}")
    return body[key]


def req_str(body, key):
    val = require(body, key)
    if not isinstance(val, str) or val == "":
        fail(errors.ERR_INVALID_REQUEST, f"Field {key} must be a non-empty string")
    return val


def opt_str(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, str):
        fail(errors.ERR_INVALID_REQUEST, f"Field {key} must be a string")
    return val


def _is_int(val):
    return isinstance(val, int) and not isinstance(val, bool)


def req_int(body, key, minimum=None):
    val = require(body, key)
    if not _is_int(val):
        fail(errors.ERR_INVALID_REQUEST, f"Field {key} must be an integer")
    if minimum is not None and val < minimum:
        fail(errors.ERR_INVALID_REQUEST, f"Field {key} must be >= {minimum}")
    return val


def opt_int(body, key, default=None, minimum=None):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not _is_int(val):
        fail(errors.ERR_INVALID_REQUEST, f"Field {key} must be an integer")
    if minimum is not None and val < minimum:
        fail(errors.ERR_INVALID_REQUEST, f"Field {key} must be >= {minimum}")
    return val


def req_number(body, key, gt=None):
    val = require(body, key)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        fail(errors.ERR_INVALID_REQUEST, f"Field {key} must be a number")
    if gt is not None and not (val > gt):
        fail(errors.ERR_INVALID_REQUEST, f"Field {key} must be > {gt}")
    return val


def req_bool(body, key, default=_MISSING):
    if key not in body or body[key] is None:
        if default is _MISSING:
            fail(errors.ERR_INVALID_REQUEST, f"Missing required field: {key}")
        return default
    val = body[key]
    if not isinstance(val, bool):
        fail(errors.ERR_INVALID_REQUEST, f"Field {key} must be a boolean")
    return val


def req_enum(body, key, allowed):
    val = require(body, key)
    if not isinstance(val, str) or val not in allowed:
        fail(errors.ERR_INVALID_REQUEST, f"Field {key} must be one of {sorted(allowed)}")
    return val


def opt_enum(body, key, allowed, default=None):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, str) or val not in allowed:
        fail(errors.ERR_INVALID_REQUEST, f"Field {key} must be one of {sorted(allowed)}")
    return val


def parse_pagination():
    """limit default 10, min 1, max 100; offset default 0. (PRD §2.3)"""
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (ValueError, TypeError):
            fail(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit_v < 1:
            limit_v = 1
        elif limit_v > 100:
            limit_v = 100
    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (ValueError, TypeError):
            fail(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset_v < 0:
            offset_v = 0
    return limit_v, offset_v


def paginate(items, limit, offset):
    return items[offset:offset + limit]
