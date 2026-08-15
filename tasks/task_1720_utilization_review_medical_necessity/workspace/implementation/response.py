"""Response envelope helpers — matches the scaffold's response_envelope spec."""
import random
import string
from flask import jsonify

from db import now_iso


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def success_object(data, status_code=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status_code


def success_list(data, total_count, limit, offset):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + limit) < total_count,
        },
        "response_type": "array",
        "data": data,
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
