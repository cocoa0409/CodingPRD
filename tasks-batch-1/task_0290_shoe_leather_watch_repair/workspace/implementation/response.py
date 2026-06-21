"""Response envelope helpers (PRD §2.2).

Success envelope:
{ "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601",
            <pagination fields on list> },
  "response_type": "object" | "array", "data": {...} }

Error envelope:
{ "meta": { "api_request_id", "api_request_timestamp" },
  "response_type": "error", "data": { "error_id", "message" } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _timestamp():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()}
    if extra:
        m.update(extra)
    return m


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def array_response(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
