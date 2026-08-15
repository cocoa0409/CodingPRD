"""Standard response envelope helpers.

Envelope shape (from SCAFFOLD response_envelope and PRD §2.2):
  success: { meta: { api_request_id, api_request_timestamp, [limit, offset, total_count, has_more] },
             response_type: "object" | "array", data: ... }
  error:   { meta: { api_request_id, api_request_timestamp },
             response_type: "error", data: { error_id, message } }
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def _now_iso():
    dt = datetime.now(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def success_object(payload, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "object",
        "data": payload if payload is not None else {},
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
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
    return jsonify(body), status


def error_response(error_id, message, status):
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
    return jsonify(body), status
