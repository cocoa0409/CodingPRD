from flask import jsonify, request

from errors import ApiError
from util import new_request_id, now_iso


def serialize(x):
    if isinstance(x, list):
        return [serialize(i) for i in x]
    if isinstance(x, dict):
        return {k: serialize(v) for k, v in x.items() if not k.startswith("_")}
    return x


def success(data, code=200, page_meta=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if page_meta:
        meta.update(page_meta)
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": serialize(data),
    }
    return jsonify(body), code


def error_body(err):
    return {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }


def page_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer", 400)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100", 400)
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer", 400)
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0", 400)
    return limit, offset


def paged(items):
    """Sort by created_at ascending (insertion order as tie-break) and paginate."""
    limit, offset = page_params()
    ordered = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(window)) < total,
    }
    return success(window, 200, page_meta=meta)
