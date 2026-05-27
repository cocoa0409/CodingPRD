"""Response envelope helpers.

Per SCAFFOLD §1.0 + PRD §2.2:

Success:
  {
    "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601", ...pagination if list... },
    "response_type": "object" | "array",
    "data": {...}
  }

Error:
  {
    "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601" },
    "response_type": "error",
    "data": { "error_id": "...", "message": "..." }
  }
"""
import secrets
import string
from flask import jsonify

import db


def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return "req_" + suffix


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.iso8601(db.now_utc()),
    }
    if extra:
        m.update(extra)
    return m


def success_object(payload, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": payload,
    }
    return jsonify(body), status


def success_array(items, *, limit, offset, total_count, status=200):
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


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
