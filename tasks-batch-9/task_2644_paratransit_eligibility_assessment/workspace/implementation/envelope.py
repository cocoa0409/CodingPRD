"""PRD 2.2 response envelope + PRD 2.3 pagination."""

from flask import jsonify, request

from errors import ApiError
from store import new_request_id, now_iso

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _meta():
    return {"api_request_id": new_request_id(), "api_request_timestamp": now_iso()}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _parse_int_param(raw):
    """A non-integer value for limit/offset is ERR_INVALID_PAGINATION."""
    if isinstance(raw, bool):
        raise ApiError("ERR_INVALID_PAGINATION")
    text = str(raw).strip()
    if not text:
        raise ApiError("ERR_INVALID_PAGINATION")
    try:
        return int(text, 10)
    except ValueError:
        raise ApiError("ERR_INVALID_PAGINATION")


def pagination():
    """PRD 2.3: limit in 1..100 (default 10); offset >= 0 (default 0)."""
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in request.args:
        limit = _parse_int_param(request.args.get("limit"))
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_INVALID_PAGINATION")
    if "offset" in request.args:
        offset = _parse_int_param(request.args.get("offset"))
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def listing(records, serializer):
    """Paginate an already-ordered, already-filtered record list."""
    limit, offset = pagination()
    total = len(records)
    page = records[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(page) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(r) for r in page],
    }
    return jsonify(body), 200
