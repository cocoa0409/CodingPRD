"""Standard response envelope helpers.

Envelope (SCAFFOLD §1.0 / PRD §2.2):
  success: { "meta": {api_request_id, api_request_timestamp, [pagination]},
             "response_type": "object"|"array", "data": {...} }
  error:   { "meta": {api_request_id, api_request_timestamp},
             "response_type": "error", "data": {error_id, message} }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _timestamp():
    # ISO 8601 UTC with three fractional digits (PRD §2.4).
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _timestamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200):
    """Single-object success response."""
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    """Array success response with pagination metadata in meta."""
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": has_more,
            }
        ),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
