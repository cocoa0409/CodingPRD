"""Response envelope helpers per PRD §2.2 / SCAFFOLD §1.0.

Success: { "meta": { api_request_id, api_request_timestamp, [pagination fields for lists] },
           "response_type": "object"|"array", "data": ... }
Error:   { "meta": { api_request_id, api_request_timestamp },
           "response_type": "error", "data": { "error_id", "message" } }
"""

import random
import string
from flask import jsonify


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _request_timestamp():
    # Envelope timestamp is server-generated wall-clock ISO8601 with 3 fractional digits.
    # (PRD example shows wall-clock style; logical clock governs entity timestamps.)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(rows, limit, offset, total_count):
    has_more = (offset + len(rows)) < total_count
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": rows,
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
