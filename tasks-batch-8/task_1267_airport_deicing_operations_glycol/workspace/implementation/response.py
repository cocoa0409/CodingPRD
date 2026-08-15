"""Standard response envelope helpers (per scaffold §1.0 / PRD §2.2)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _now_iso():
    now = datetime.now(timezone.utc)
    # ISO 8601 UTC with three fractional digits, trailing Z.
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def success_object(data, http_status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), http_status


def success_list(items, limit, offset, total_count):
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
    return jsonify(body), 200


def error_body(error_id, message):
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
    return body


def error_response(error_id, http_status, message):
    return jsonify(error_body(error_id, message)), http_status
