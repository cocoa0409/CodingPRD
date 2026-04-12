import uuid
from flask import jsonify
from db import now_iso


def success_response(data, status_code=200, response_type="object"):
    body = {
        "meta": {
            "api_request_id": "req_rm_" + uuid.uuid4().hex[:12],
            "api_request_timestamp": now_iso(),
        },
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status_code


def list_response(data, total_count, limit, offset):
    has_more = (offset + limit) < total_count
    body = {
        "meta": {
            "api_request_id": "req_rm_" + uuid.uuid4().hex[:12],
            "api_request_timestamp": now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": data,
    }
    return jsonify(body), 200


def error_response(error_id, message, status_code):
    body = {
        "meta": {
            "api_request_id": "req_rm_" + uuid.uuid4().hex[:12],
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status_code
