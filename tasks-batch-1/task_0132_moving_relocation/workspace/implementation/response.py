"""Standard response envelope helpers.

Envelope shape is taken verbatim from PRD §2.2 / SCAFFOLD §1.0:

    success:
      { "meta": { "api_request_id": "req_xxx",
                  "api_request_timestamp": "ISO8601",
                  [pagination fields for lists] },
        "response_type": "object" | "array",
        "data": {} }
    error:
      { "meta": { api_request_id, api_request_timestamp },
        "response_type": "error",
        "data": { "error_id": "...", "message": "..." } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    # "req_" prefix per PRD §2.2: api_request_id starts with req_.
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _timestamp():
    # ISO 8601 UTC with three fractional digits (PRD §2.2 / §2.4).
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


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def array_response(data, limit, offset, total_count, status=200):
    has_more = (offset + len(data)) < total_count
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }
    )
    body = {
        "meta": meta,
        "response_type": "array",
        "data": data,
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
