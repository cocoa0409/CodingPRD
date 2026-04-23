import uuid
from flask import jsonify
from clock import logical_clock


def make_request_id():
    return "req_" + uuid.uuid4().hex[:20]


def success_response(data, status_code=200, pagination=None):
    meta = {
        "api_request_id": make_request_id(),
        "api_request_timestamp": logical_clock.format_timestamp(),
    }
    response_type = "object"
    if isinstance(data, list):
        response_type = "array"
    if pagination:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status_code


def error_response(error_id, message, status_code):
    body = {
        "meta": {
            "api_request_id": make_request_id(),
            "api_request_timestamp": logical_clock.format_timestamp(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status_code
