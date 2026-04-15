"""Standard response envelope helpers."""

from flask import jsonify
from db import new_id, now_iso


def _make_meta(**extra):
    m = {
        "api_request_id": "req_" + new_id().replace("-", "")[:12],
        "api_request_timestamp": now_iso(),
    }
    m.update(extra)
    return m


def success_response(data, status_code=200, response_type="object"):
    body = {
        "meta": _make_meta(),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status_code


def list_response(items, total_count, limit, offset):
    has_more = (offset + limit) < total_count
    body = {
        "meta": _make_meta(
            limit=limit,
            offset=offset,
            total_count=total_count,
            has_more=has_more,
        ),
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
