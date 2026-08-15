"""Response envelope helpers per SCAFFOLD response_envelope / PRD section 2.2."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _request_ts():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def success(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_ts(),
        },
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_ts(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + limit) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error(error_id, status, message):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_ts(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
