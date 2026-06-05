"""Response envelope helpers.

Envelope shape is fixed by PRD §2.2 / SCAFFOLD response_envelope:
  success: { "meta": {...}, "response_type": "object"|"array", "data": {...} }
  error:   { "meta": {...}, "response_type": "error", "data": {error_id, message} }

meta carries api_request_id (req_ prefix) and api_request_timestamp
(ISO 8601 UTC, 3 fractional digits). For list endpoints, pagination fields
limit/offset/total_count/has_more are added to meta.
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALPHANUM = string.ascii_uppercase + string.ascii_lowercase + string.digits


def now_iso():
    # ISO 8601 UTC with exactly 3 fractional digits and a trailing Z.
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(pagination=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}
    if pagination is not None:
        m.update(pagination)
    return m


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_list(items, limit, offset, total_count, status=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return success(items, status=status, response_type="array", pagination=pagination)


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
