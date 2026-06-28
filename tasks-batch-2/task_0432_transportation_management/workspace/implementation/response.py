"""Response envelope helpers (PRD §2.2).

Success envelope:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601",
              [pagination fields for lists] },
    "response_type": "object" | "array", "data": ... }

Error envelope:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error",
    "data": { "error_id", "message" } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    # api_request_id is server-generated and starts with "req_" (PRD §2.2).
    alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _now_iso():
    # ISO 8601 UTC with exactly three fractional digits (PRD §2.2 / §2.4).
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }


def success(data, status=200, pagination=None):
    """Single-object (or empty-object) success response. response_type=object."""
    meta = _base_meta()
    if pagination:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, pagination, status=200):
    """List success response. response_type=array; pagination fields in meta."""
    meta = _base_meta()
    meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error(error_id, message, status):
    meta = _base_meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
