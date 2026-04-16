"""Standard response envelope helpers."""

import uuid
from flask import jsonify
from db import now_iso


def success_object(data, status_code=200):
    body = {
        "meta": {
            "api_request_id": f"req_{uuid.uuid4().hex[:16]}",
            "api_request_timestamp": now_iso(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status_code


def success_list(items, total_count, limit, offset):
    body = {
        "meta": {
            "api_request_id": f"req_{uuid.uuid4().hex[:16]}",
            "api_request_timestamp": now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + limit) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": f"req_{uuid.uuid4().hex[:16]}",
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
