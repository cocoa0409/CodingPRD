"""Response envelope helpers.

Envelope is FIXED by SCAFFOLD §1.0 and PRD §2.2:
  success: { "meta": {api_request_id, api_request_timestamp, [pagination]},
             "response_type": "object"|"array", "data": ... }
  error:   { "meta": {...}, "response_type": "error",
             "data": { "error_id", "message" } }

Timestamps: ISO 8601 UTC with three fractional digits (PRD §2.2/§2.4).
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional (millisecond) digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination:
        meta.update(pagination)
    return meta


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def array_response(items, limit, offset, total_count, status=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
