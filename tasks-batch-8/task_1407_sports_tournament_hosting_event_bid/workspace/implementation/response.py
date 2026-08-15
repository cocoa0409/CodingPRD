"""Response envelope helpers (PRD §2.2 / §2.3).

Success: { "meta": {api_request_id, api_request_timestamp[, limit, offset,
           total_count, has_more]}, "response_type": "object"|"array", "data": ... }
Error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error", "data": {"error_id", "message"} }
"""

import secrets
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    return "req_" + secrets.token_hex(10)


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def ok(data, status=200, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def error_envelope(error_id, status, message):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
