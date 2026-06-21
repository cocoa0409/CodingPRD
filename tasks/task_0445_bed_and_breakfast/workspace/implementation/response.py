"""Response envelope helpers (PRD §2.2).

Success:
  { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": ISO8601,
              [pagination fields for lists] },
    "response_type": "object" | "array", "data": {...} }
Error:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error",
    "data": { "error_id", "message" } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    # PRD: a server-generated unique identifier for the request that starts with req_.
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _timestamp():
    # ISO 8601 UTC with three fractional digits (milliseconds).
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _timestamp(),
    }


def success(data, status=200, response_type="object"):
    body = {
        "meta": _base_meta(),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def list_success(items, limit, offset, total_count):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error(error_id, http_status, message):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
