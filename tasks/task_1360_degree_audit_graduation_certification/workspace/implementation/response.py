"""Response envelope helpers per SCAFFOLD `response_envelope` and PRD §2.2.

Success envelope:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601",
              [pagination fields for lists] },
    "response_type": "object" | "array",
    "data": ... }

Error envelope:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error",
    "data": { "error_id": "...", "message": "..." } }
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

from errors import ApiError


def _new_request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=22))
    return "req_" + suffix


def _now_iso():
    """ISO 8601 UTC with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(extra=None):
    m = {
        "api_request_id": _new_request_id(),
        "api_request_timestamp": _now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def success_object(data, http_status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), http_status


def success_list(items, limit, offset, total_count):
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
    return jsonify(body), 200


def error_response(err: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
