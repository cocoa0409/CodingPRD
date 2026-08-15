"""Standard response envelope helpers (scaffold response_envelope)."""

import random
import string
import time
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def _envelope_timestamp():
    # Wall-clock timestamp with exactly three fractional digits (PRD 2.2).
    now = time.time()
    dt = datetime.fromtimestamp(now, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(dt.microsecond / 1000):03d}Z"


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _envelope_timestamp(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_array(items, limit, offset, total_count, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _envelope_timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id, http_status, message):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _envelope_timestamp(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
