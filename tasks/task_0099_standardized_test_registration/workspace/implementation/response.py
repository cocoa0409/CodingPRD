"""Standard response envelope helpers.

Envelope shape (from SCAFFOLD response_envelope + PRD §2.2):

    {
      "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601",
                 [list-only: "limit", "offset", "total_count", "has_more"] },
      "response_type": "object" | "array" | "error",
      "data": {} | [] | { "error_id": ..., "message": ... }
    }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _now_iso_ms():
    # ISO 8601 UTC with exactly three fractional digits, e.g. 2025-05-24T10:30:00.123Z
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso_ms(),
    }


def object_response(data, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


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
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
