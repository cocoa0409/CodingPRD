"""Standard response envelope (PRD 2.2).

Success: { "meta": {api_request_id, api_request_timestamp[, limit, offset,
           total_count, has_more]}, "response_type": "object"|"array", "data": ... }
Error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error", "data": {"error_id", "message"} }
"""

import uuid

from flask import jsonify

from util import now_iso


def _meta(pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": now_iso(),
    }
    if pagination:
        meta.update(pagination)
    return meta


def ok_object(data, status=200):
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }), status


def ok_list(items, pagination, status=200):
    return jsonify({
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }), status


def error_response(error_id, message, status):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status
