"""Shared request-validation helpers implementing the PRD §2.8 priority ladder pieces."""
from flask import request, g

from errors import ApiError
from util import to_decimal, parse_date


def require_roles(*roles):
    if g.user_role not in roles:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this endpoint")


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return data


def _missing(k):
    raise ApiError("ERR_VALIDATION", 400, "Missing required field: %s" % k)


def req_str(d, k):
    v = d.get(k)
    if not isinstance(v, str):
        _missing(k)
    return v


def opt_str(d, k):
    v = d.get(k)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be a string" % k)
    return v


def req_num(d, k):
    if k not in d or d[k] is None:
        _missing(k)
    try:
        return to_decimal(d[k])
    except (ValueError, ArithmeticError):
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be a number" % k)


def opt_num(d, k):
    if k not in d or d[k] is None:
        return None
    try:
        return to_decimal(d[k])
    except (ValueError, ArithmeticError):
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be a number" % k)


def req_int(d, k):
    v = d.get(k)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be an integer" % k)
    return v


def req_enum(d, k, allowed):
    v = req_str(d, k)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be one of %s" % (k, ", ".join(allowed)))
    return v


def req_date(d, k):
    v = req_str(d, k)
    try:
        parse_date(v)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be an ISO 8601 date" % k)
    return v


def req_str_list(d, k):
    v = d.get(k)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be an array of strings" % k)
    return v


def pagination_params():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", 400, "offset must be non-negative")
    return limit, offset


def paginate(items, serializer):
    from envelope import success
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success([serializer(e) for e in page], 200, "array", {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    })


def get_or_404(store, entity_id, label="Resource"):
    e = store.get(entity_id)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "%s not found: %s" % (label, entity_id))
    return e
