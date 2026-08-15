"""Schema/format validation (pipeline stage 1) and pagination helpers."""
from flask import request

import db
from errors import (
    ERR_INVALID_REQUEST,
    ApiError,
)


def _bad(message):
    raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], message)


def get_body():
    """Return the request JSON body as a dict; {} when empty. 400 if malformed."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        _bad("Request body is not valid JSON")
    if not isinstance(data, dict):
        _bad("Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, key):
    v = body.get(key)
    if v is None:
        _bad("Missing required field: %s" % key)
    if not isinstance(v, str) or v == "":
        _bad("Field %s must be a non-empty string" % key)
    return v


def opt_str(body, key, default=None):
    v = body.get(key)
    if v is None:
        return default
    if not isinstance(v, str):
        _bad("Field %s must be a string" % key)
    return v


def req_int(body, key, minimum=None, maximum=None):
    v = body.get(key)
    if v is None:
        _bad("Missing required field: %s" % key)
    if not _is_int(v):
        _bad("Field %s must be an integer" % key)
    if minimum is not None and v < minimum:
        _bad("Field %s is out of range" % key)
    if maximum is not None and v > maximum:
        _bad("Field %s is out of range" % key)
    return v


def opt_int(body, key, default=None, minimum=None, maximum=None):
    v = body.get(key)
    if v is None:
        return default
    if not _is_int(v):
        _bad("Field %s must be an integer" % key)
    if minimum is not None and v < minimum:
        _bad("Field %s is out of range" % key)
    if maximum is not None and v > maximum:
        _bad("Field %s is out of range" % key)
    return v


def opt_bool(body, key, default=None):
    v = body.get(key)
    if v is None:
        return default
    if not isinstance(v, bool):
        _bad("Field %s must be a boolean" % key)
    return v


def req_enum(body, key, allowed):
    v = body.get(key)
    if v is None:
        _bad("Missing required field: %s" % key)
    if not isinstance(v, str) or v not in allowed:
        _bad("Field %s must be one of %s" % (key, ", ".join(sorted(allowed))))
    return v


def opt_enum(body, key, allowed, default=None):
    v = body.get(key)
    if v is None:
        return default
    if not isinstance(v, str) or v not in allowed:
        _bad("Field %s must be one of %s" % (key, ", ".join(sorted(allowed))))
    return v


def req_date(body, key):
    v = body.get(key)
    if v is None:
        _bad("Missing required field: %s" % key)
    d = db.parse_date(v)
    if d is None:
        _bad("Field %s must be a YYYY-MM-DD date" % key)
    return v


def req_datetime(body, key):
    v = body.get(key)
    if v is None:
        _bad("Missing required field: %s" % key)
    dt = db.parse_datetime(v)
    if dt is None:
        _bad("Field %s must be an ISO8601 datetime" % key)
    return dt


def req_month(body, key):
    v = body.get(key)
    if v is None:
        _bad("Missing required field: %s" % key)
    if not db.valid_month(v):
        _bad("Field %s must be a YYYY-MM month" % key)
    return v


def opt_minute(body, key, default=None):
    """Minutes-since-midnight optional field, 0..1439."""
    return opt_int(body, key, default=default, minimum=0, maximum=1439)


def req_minute(body, key):
    return req_int(body, key, minimum=0, maximum=1439)


def pagination_params():
    """Validate limit/offset query params; defaults limit=10, offset=0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw, 10)
        except (ValueError, TypeError):
            _bad("limit must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw, 10)
        except (ValueError, TypeError):
            _bad("offset must be an integer")
        if offset < 0:
            _bad("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (stable via insertion seq) and slice."""
    ordered = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset : offset + limit]
    info = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return [db.public(r) for r in page], info
