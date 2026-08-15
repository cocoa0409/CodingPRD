"""Request body shape validation and pagination helpers (ladder rung 4)."""

import re

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST

_PERIOD_RE = re.compile(r"^(\d{4})-Q([1-4])$")


def get_body():
    """Return the request JSON body as a dict, else raise ERR_INVALID_REQUEST."""
    body = request.get_json(silent=True)
    if body is None:
        # Some clients omit Content-Type: application/json; try a raw parse.
        raw = request.get_data(cache=True)
        if raw:
            import json as _json

            try:
                body = _json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                body = None
        if body is None:
            body = {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' is required and must be a string" % field)
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be a string" % field)
    return v


def req_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' is required and must be an integer" % field)
    return v


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be an integer" % field)
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "Field '%s' must be one of %s" % (field, ", ".join(allowed)),
        )
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    return req_enum(body, field, allowed)


def req_period(body, field):
    v = req_str(body, field)
    if not _PERIOD_RE.match(v):
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "Field '%s' must match the quarterly format YYYY-Qn with n in 1..4" % field,
        )
    return v


def quarter_index(period):
    """Convert 'YYYY-Qn' to year * 4 + (n - 1). Assumes validated format."""
    year = int(period[0:4])
    q = int(period[-1])
    return year * 4 + (q - 1)


def req_list(body, field):
    v = body.get(field)
    if not isinstance(v, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' is required and must be a list" % field)
    return v


def opt_int_list(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be a list of integers" % field)
    for item in v:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be a list of integers" % field)
    return v


def parse_pagination():
    """Parse limit/offset query params with defaults limit=10, offset=0.

    Invalid (non-integer) values fall back to defaults. Out-of-range values are
    clamped: limit to [1, 100], offset to >= 0.
    """
    try:
        limit = int(request.args.get("limit", "10"))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """Slice items and build the pagination block for the meta envelope."""
    total = len(items)
    page = items[offset : offset + limit]
    has_more = (offset + limit) < total
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }


def sorted_by_creation(items):
    """Sort by (created_at, creation sequence) ascending."""
    return sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
