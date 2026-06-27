"""Response envelope helpers (PRD §2.2, scaffold §1.0).

Success: { "meta": {...}, "response_type": "object"|"array", "data": {...} }
Error:   { "meta": {...}, "response_type": "error", "data": {error_id, message} }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


_ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _timestamp():
    # api_request_timestamp: server-generated ISO 8601 UTC with three fractional
    # digits (PRD §2.2). This is the real server clock, distinct from the
    # logical clock used for temporal business reasoning.
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()}
    if extra:
        m.update(extra)
    return m


def success(data, status=200, meta_extra=None):
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(meta_extra),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def paginated(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return success(items, status=200, meta_extra=meta_extra)


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
