"""Response envelope helpers (PRD §2.2, scaffold §1.0).

success: { "meta": { api_request_id, api_request_timestamp [, limit, offset,
                     total_count, has_more] },
           "response_type": "object" | "array", "data": {} }
error:   { "meta": {...}, "response_type": "error",
           "data": { "error_id", "message" } }

The api_request_timestamp is a server-generated ISO 8601 UTC timestamp with
three fractional digits. It is a real-time stamp on the envelope (not the
logical clock), per PRD §2.2.
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }


def success(data, status=200):
    """Single-object / generic success response (response_type=object)."""
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def list_success(items, limit, offset, total_count, status=200):
    """List response (response_type=array) with pagination fields in meta."""
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


def error_body(error_id, message):
    return {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
