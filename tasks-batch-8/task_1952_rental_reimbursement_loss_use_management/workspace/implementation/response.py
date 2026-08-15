from flask import jsonify

from errors import ApiError, api_error
from util import now_ts, request_id


def ok(data, status=200, response_type="object", pagination=None):
    meta = {"api_request_id": request_id(), "api_request_timestamp": now_ts()}
    if pagination is not None:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def error_response(err):
    body = {
        "meta": {"api_request_id": request_id(), "api_request_timestamp": now_ts()},
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def paginate(items, args):
    """limit/offset pagination: limit defaults to 10, min 1, clamped to 100; offset defaults to 0."""
    raw_limit = args.get("limit")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise api_error("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1:
            raise api_error("ERR_INVALID_REQUEST", 400, "limit must be at least 1")
        if limit > 100:
            limit = 100
    raw_offset = args.get("offset")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise api_error("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise api_error("ERR_INVALID_REQUEST", 400, "offset must be non-negative")
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    meta = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    return page, meta
