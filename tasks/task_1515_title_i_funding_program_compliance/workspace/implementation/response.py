"""Standard response envelope per PRD section 2.2 / scaffold response_envelope."""

import uuid
from flask import jsonify

import db


def _request_id():
    return "req_" + uuid.uuid4().hex[:20]


def success_object(data, http_status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": db.now_ts(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), http_status


def success_list(items, limit, offset, total_count):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": db.now_ts(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": db.now_ts(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
