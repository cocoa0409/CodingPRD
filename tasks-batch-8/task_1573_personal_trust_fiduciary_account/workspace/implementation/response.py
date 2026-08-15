"""Standard response envelope helpers (per SCAFFOLD response_envelope)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta_timestamp():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def ok(data, status=200, response_type="object"):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _meta_timestamp(),
        },
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _meta_timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _meta_timestamp(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
