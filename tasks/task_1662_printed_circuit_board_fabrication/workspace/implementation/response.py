"""Response envelope helpers matching the scaffold's response_envelope spec."""

import secrets
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(24))


def _timestamp():
    now = datetime.now(timezone.utc)
    # ISO 8601 UTC with three fractional digits
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta(pagination=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _timestamp(),
    }
    if pagination:
        m["limit"] = pagination["limit"]
        m["offset"] = pagination["offset"]
        m["total_count"] = pagination["total_count"]
        m["has_more"] = pagination["has_more"]
    return m


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
