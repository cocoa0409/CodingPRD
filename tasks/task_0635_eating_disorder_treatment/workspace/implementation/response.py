"""Standard response envelope helpers.

Envelope shape is taken verbatim from PRD §2.2 and SCAFFOLD response_envelope:
  success: { "meta": {api_request_id, api_request_timestamp, [pagination...]},
             "response_type": "object"|"array", "data": {...} }
  error:   { "meta": {api_request_id, api_request_timestamp},
             "response_type": "error",
             "data": {"error_id": "...", "message": "..."} }

api_request_timestamp is the wall-clock instant at which the response is built,
formatted ISO 8601 UTC with three fractional digits (PRD §2.2). This is the
*response metadata* timestamp; it is distinct from the logical clock that stamps
business records (PRD §2.4).
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    # PRD §2.2: "a server-generated unique identifier for the request that
    # starts with req_".
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(random.choices(alphabet, k=20))
    return "req_" + suffix


def _now_iso_millis():
    # ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso_millis(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def list_response(items, limit, offset, total_count):
    # has_more is True when there are records beyond this page (PRD §2.3).
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return success(items, status=200, response_type="array", pagination=pagination)


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
