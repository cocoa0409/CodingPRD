import uuid
from flask import jsonify
import clock


def generate_request_id():
    return "req_" + uuid.uuid4().hex[:20]


def success_response(data, status_code=200, response_type="object", pagination=None):
    meta = {
        "api_request_id": generate_request_id(),
        "api_request_timestamp": clock.format_timestamp(clock.now()),
    }
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


def make_error_response(error_id, message, status_code):
    meta = {
        "api_request_id": generate_request_id(),
        "api_request_timestamp": clock.format_timestamp(clock.now()),
    }
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status_code
