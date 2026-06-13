"""Standard response envelope helpers (PRD §2.2).

Success envelope:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": ISO8601,
              [limit, offset, total_count, has_more for lists] },
    "response_type": "object" | "array",
    "data": {} }

Error envelope:
  { "meta": { api_request_id, api_request_timestamp },
    "response_type": "error",
    "data": { "error_id": ..., "message": ... } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    # api_request_id starts with "req_" (PRD §2.2).
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def now_iso():
    # ISO 8601 UTC timestamp with three fractional digits (PRD §2.2 / §2.4).
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, pagination=None):
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
