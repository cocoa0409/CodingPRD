"""Response envelope helpers (PRD §2.2, SCAFFOLD §1.0).

Success: { "meta": {...}, "response_type": "object"|"array", "data": ... }
Error:   { "meta": {...}, "response_type": "error",
           "data": { "error_id": "...", "message": "..." } }

meta always carries api_request_id (req_ prefix) and api_request_timestamp
(ISO 8601 UTC, three fractional digits). List responses add limit/offset/
total_count/has_more to meta.
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

from timeutil import format_iso


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": format_iso(datetime.now(timezone.utc)),
    }


def success(data, status=200, is_array=False, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {
        "meta": meta,
        "response_type": "array" if is_array else "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
