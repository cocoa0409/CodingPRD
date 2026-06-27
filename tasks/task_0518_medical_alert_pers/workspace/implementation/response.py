"""Standard response envelope helpers (PRD 2.2).

success:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": ISO8601[,
              limit, offset, total_count, has_more] },
    "response_type": "object" | "array", "data": {...} }
error:
  { "meta": { api_request_id, api_request_timestamp },
    "response_type": "error", "data": { "error_id": ..., "message": ... } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALNUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _timestamp():
    # PRD 2.2: server-generated ISO 8601 UTC timestamp with three fractional digits.
    # This is a real wall-clock stamp of when the response is built (not the logical
    # clock — the logical clock governs domain time only).
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()}
    if extra:
        m.update(extra)
    return m


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def array_response(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
