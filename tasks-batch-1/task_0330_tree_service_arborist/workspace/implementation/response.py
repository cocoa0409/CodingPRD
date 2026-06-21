"""Standard response envelope helpers per PRD section 2.2.

Success envelope:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601",
              [list-only: "limit","offset","total_count","has_more"] },
    "response_type": "object" | "array",
    "data": {} | [] }

Error envelope:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error",
    "data": { "error_id", "message" } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200):
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def paginated(items, limit, offset, total_count):
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
    return jsonify(body), 200


def error(error_id, http_status, message=None):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    return jsonify(body), http_status
