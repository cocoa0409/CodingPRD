"""Standard response envelope helpers (PRD §2.2)."""
from flask import jsonify

import util


def _meta(pagination=None):
    meta = {
        "api_request_id": util.request_id(),
        "api_request_timestamp": util.iso_now(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, status=200):
    """Single-object success envelope. response_type = 'object'."""
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    """List success envelope with pagination bookkeeping in meta."""
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error(error_id, message, status):
    """Error envelope. response_type = 'error'."""
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
