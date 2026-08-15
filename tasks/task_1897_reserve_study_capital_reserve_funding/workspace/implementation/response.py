"""Standard response envelope helpers."""

import uuid
from flask import jsonify
from db import store


def _make_meta():
    return {
        "api_request_id": f"req_{uuid.uuid4().hex[:24]}",
        "api_request_timestamp": store.now_iso(),
    }


def success_object(data, status_code=200):
    body = {
        "meta": _make_meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status_code


def success_list(items, total_count, limit, offset):
    meta = _make_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _make_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
