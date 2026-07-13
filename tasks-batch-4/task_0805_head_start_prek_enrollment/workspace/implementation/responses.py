"""Standard response envelope helpers."""

from flask import jsonify

import store


def _meta(pagination=None):
    meta = {
        "api_request_id": store.request_id(),
        "api_request_timestamp": store.real_now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
