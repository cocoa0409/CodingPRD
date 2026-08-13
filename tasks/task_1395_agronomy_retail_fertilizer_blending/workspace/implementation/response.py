"""Standard response envelope helpers.

Success:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601" },
    "response_type": "object" | "array", "data": {} }
Error:
  { "meta": {...}, "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }
List responses add limit/offset/total_count/has_more inside meta.
"""

import secrets
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _ts() -> str:
    return iso8601_ms(datetime.now(timezone.utc))


def iso8601_ms(dt: datetime) -> str:
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def success_object(data, status=200):
    body = {
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": _ts()},
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _ts(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + limit < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error(error_id, message, http_status):
    body = {
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": _ts()},
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
