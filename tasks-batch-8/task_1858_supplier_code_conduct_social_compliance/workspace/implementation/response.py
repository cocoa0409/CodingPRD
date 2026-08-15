"""Response envelope helpers."""
import random
import string
from flask import jsonify
import db


def _request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return f"req_{suffix}"


def _now_iso():
    """Timestamp from the program logical clock (3 fractional digits)."""
    return db.get_clock()


def success_object(data, status_code=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status_code


def success_array(items, total_count, limit, offset, status_code=200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status_code


def error_body(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
