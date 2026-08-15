"""Standard response envelope helpers per PRD §2.2 / §2.3.

Success: {"meta": {"api_request_id", "api_request_timestamp", [limit, offset,
          total_count, has_more]}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}

Note: api_request_timestamp is a real server timestamp (ISO 8601 UTC, three
fractional digits) — it is deliberately NOT the logical shop clock.
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def _server_ts():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def success(data, status=200, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _server_ts(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def error(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _server_ts(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
