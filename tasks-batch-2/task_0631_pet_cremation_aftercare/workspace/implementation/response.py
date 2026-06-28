"""Standard response envelope helpers (PRD section 2.2).

Success:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601",
              [pagination fields for list endpoints] },
    "response_type": "object" | "array", "data": {...} }

Error:
  { "meta": { "api_request_id": "...", "api_request_timestamp": "..." },
    "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }

The api_request_timestamp is a wall-clock ISO 8601 UTC timestamp with three
fractional digits (it is request metadata, not a domain timestamp, so it is NOT
sourced from the logical clock).
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(random.choices(_ALPHANUM, k=20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
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


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
