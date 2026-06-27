"""Response envelope helpers (PRD §2.2, FIXED envelope).

   { meta: {api_request_id, api_request_timestamp, [pagination]},
     response_type: "object"|"array"|"error", data: {...} }

api_request_id starts with "req_"; api_request_timestamp is an ISO 8601 UTC
timestamp with three fractional digits (PRD §2.2). The request timestamp is
wall-clock (it stamps the HTTP response, not domain state)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alnum = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "req_" + "".join(random.choice(alnum) for _ in range(20))


def _now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": _now_iso()}
    if extra:
        m.update(extra)
    return m


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
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


def empty_response(status=200):
    body = {"meta": _meta(), "response_type": "object", "data": {}}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
