"""Response envelope helpers (PRD sections 2.2 and 2.3)."""
from flask import jsonify, request

import store
from errors import ApiError, fail

PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": store.request_id(),
        "api_request_timestamp": store.iso_now(),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    try:
        value = int(text, 10)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    if value < minimum or (maximum is not None and value > maximum):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is out of range." % name)
    return value


def pagination():
    """Returns (limit, offset), validating range per PRD section 2.3."""
    limit = _int_param("limit", PAGE_DEFAULT_LIMIT, PAGE_MIN_LIMIT, PAGE_MAX_LIMIT)
    offset = _int_param("offset", PAGE_DEFAULT_OFFSET, 0, None)
    return limit, offset


def paginate(rows, serializer):
    """Sort by created_at ascending, count, then slice."""
    limit, offset = pagination()
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)
