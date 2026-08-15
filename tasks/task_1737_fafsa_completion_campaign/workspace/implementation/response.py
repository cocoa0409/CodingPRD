"""Standard response envelope helpers (scaffold §1.0)."""

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


def success_list(items, limit, offset, total_count, status_code=200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status_code


def error_response(error_id, http_status, message):
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
