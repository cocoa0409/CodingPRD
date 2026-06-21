"""Standard response envelope helpers.

Envelope shape is fixed by SCAFFOLD §1.0 / PRD §2.2:

    success: { "meta": {...}, "response_type": "object"|"array", "data": {...} }
    error:   { "meta": {...}, "response_type": "error",
               "data": { "error_id": "...", "message": "..." } }

meta always carries api_request_id (prefixed "req_") and api_request_timestamp
(ISO 8601 UTC, ms precision). List responses add limit/offset/total_count/has_more
to meta.
"""

import secrets
import string
from datetime import datetime, timezone

from flask import jsonify

from timeutil import iso

_ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(_ALPHANUM) for _ in range(20))


def _base_meta():
    return {
        "api_request_id": _request_id(),
        # Response envelope timestamp is real wall-clock UTC, independent of the
        # test-driving logical clock.
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }


def success(data, status=200, response_type="object", pagination=None):
    meta = _base_meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def object_response(data, status=200):
    return success(data, status=status, response_type="object")


def array_response(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return success(items, status=200, response_type="array", pagination=pagination)


def error_response(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
