"""Response envelope helpers per PRD section 2.2 (scaffold response_envelope).

success: { "meta": { "api_request_id", "api_request_timestamp", [pagination] },
           "response_type": "object" | "array", "data": {} }
error:   { "meta": {...}, "response_type": "error",
           "data": { "error_id", "message" } }
"""
import random
import string
from datetime import timezone

from flask import jsonify

from clock import clock


def _request_id():
    alphanum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphanum) for _ in range(20))


def _iso_ms(dt):
    """ISO 8601 UTC with three fractional digits (PRD 2.2/2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(extra=None):
    # api_request_timestamp is a server-generated ISO 8601 UTC timestamp with
    # three fractional digits. We use the logical clock for determinism.
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _iso_ms(clock.now()),
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
    resp = jsonify(body)
    resp.status_code = status
    return resp


def list_success(items, limit, offset, total_count, status=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    return success(items, status=status, response_type="array", pagination=pagination)


def error_response(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body
