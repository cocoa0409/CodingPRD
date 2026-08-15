"""Response envelope helpers implementing PRD §2.2 verbatim."""

from flask import jsonify, request

import db


def _meta():
    return {
        "api_request_id": db.new_request_id(),
        "api_request_timestamp": db.now_iso(),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items):
    """List envelope with PRD §2.3 pagination: limit default 10, min 1,
    max 100; offset default 0. Meta carries limit/offset/total_count/has_more."""
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": page}), 200


def err(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
