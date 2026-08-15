"""Standard response envelope helpers (success object/array + pagination)."""
from flask import jsonify, request

import db
from errors import err


def _meta():
    return {
        "api_request_id": db.new_request_id(),
        "api_request_timestamp": db.iso(db.now()),
    }


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": db.pub(data)}
    return jsonify(body), status


def _parse_pagination():
    """Parse limit/offset query params. Defaults 10/0, limit min 1, max 100."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            raise err("ERR_INVALID_REQUEST", "limit must be at least 1")
        if limit > 100:
            limit = 100
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be at least 0")
    return limit, offset


def sort_items(items):
    """Default list ordering: created_at ascending (insertion order breaks ties)."""
    return sorted(items, key=lambda e: (e.get("created_at"), e.get("_seq", 0)))


def success_list(items, status=200):
    items = sort_items(items)
    limit, offset = _parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array", "data": db.pub(page)}
    return jsonify(body), status


def success_array(data, status=200):
    """Array response without pagination (e.g. PUT splits result)."""
    body = {"meta": _meta(), "response_type": "array", "data": db.pub(data)}
    return jsonify(body), status


def error_response(api_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    return jsonify(body), api_err.http_status
