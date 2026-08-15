"""Standard response envelope helpers.

Envelope format per PRD §2.2:
  success: { "meta": {"api_request_id": ..., "api_request_timestamp": ..., [pagination]},
             "response_type": "object" | "array", "data": {} }
  error:   { "meta": {"api_request_id": ..., "api_request_timestamp": ...},
             "response_type": "error", "data": {"error_id": ..., "message": ...} }
"""

import random
import string
from flask import jsonify


def _gen_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=24))
    return f"req_{suffix}"


def _request_timestamp() -> str:
    from clock import now_iso
    return now_iso()


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": _gen_request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _gen_request_id(),
            "api_request_timestamp": _request_timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": {
            "api_request_id": _gen_request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
