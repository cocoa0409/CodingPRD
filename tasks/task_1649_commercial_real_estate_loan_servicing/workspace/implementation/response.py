"""Standard response envelope helpers per scaffold response_envelope."""
import uuid
from datetime import datetime, timezone

from flask import jsonify


def _meta(pagination=None):
    m = {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z",
    }
    if pagination is not None:
        m["limit"] = pagination["limit"]
        m["offset"] = pagination["offset"]
        m["total_count"] = pagination["total_count"]
        m["has_more"] = pagination["has_more"]
    return m


def success(data, status=200, pagination=None, is_array=False):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if is_array else "object",
        "data": data,
    }
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
