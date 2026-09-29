"""Response envelope (PRD 2.2) and pagination (PRD 2.3)."""
from flask import jsonify, request

from errors import ApiError
from store import fmt_dt, now, request_id, serialize

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
PAGE_OFFSET_MIN = 0


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def ok_array(items, status=200):
    """A 2xx array payload that is not a paginated list endpoint."""
    body = {"meta": _meta(), "response_type": "array", "data": items}
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def _int_param(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be at most %d." % (name, maximum))
    return value


def pagination():
    limit = _int_param("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _int_param("offset", PAGE_OFFSET_DEFAULT, PAGE_OFFSET_MIN, None)
    return limit, offset


def paginate(records, serializer=serialize):
    """Apply pagination to an already-filtered, already-ordered record list."""
    limit, offset = pagination()
    total = len(records)
    page = records[offset:offset + limit]
    return ok_list([serializer(r) for r in page], total, limit, offset)
