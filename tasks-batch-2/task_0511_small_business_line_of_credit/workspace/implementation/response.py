"""Standard response envelope helpers (PRD §2.2, SCAFFOLD response_envelope).

success: { "meta": { "api_request_id", "api_request_timestamp", [pagination] },
           "response_type": "object" | "array", "data": {} }
error:   { "meta": { ... }, "response_type": "error",
           "data": { "error_id", "message" } }

api_request_timestamp is a server-generated ISO 8601 UTC timestamp with three
fractional digits. It records when the request is served, using REAL wall-clock
time (it is a server-generated request identifier timestamp, distinct from the
logical clock that governs business-time evaluations).
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alphanum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphanum, k=20))


def _now_iso_millis():
    # Real wall-clock for the request envelope timestamp, 3 fractional digits.
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso_millis(),
    }
    if pagination is not None:
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
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
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
