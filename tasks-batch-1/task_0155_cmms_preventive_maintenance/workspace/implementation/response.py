"""Standard response-envelope helpers.

Envelope shape (PRD §2.2 / SCAFFOLD response_envelope):

  success:
    { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": ISO8601,
                [pagination fields for lists] },
      "response_type": "object" | "array",
      "data": {} | [] }

  error:
    { "meta": { "api_request_id", "api_request_timestamp" },
      "response_type": "error",
      "data": { "error_id": "...", "message": "..." } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _now_iso():
    # ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.2).
    # This is the request envelope timestamp — a system-managed wall-clock
    # instant, distinct from the test-driving logical clock (PRD §2.9).
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }


def object_response(data, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def array_response(items, limit, offset, total_count, status=200):
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
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
