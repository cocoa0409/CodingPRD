"""Standard response envelope helpers (PRD §2.2, SCAFFOLD §1.0).

Success (object):  { "meta": {api_request_id, api_request_timestamp}, "response_type": "object", "data": {...} }
Success (array):   meta additionally carries limit/offset/total_count/has_more.
Error:             { "meta": {...}, "response_type": "error", "data": {error_id, message} }
"""

import datetime
import random
import string

from flask import jsonify

from db import format_iso8601_millis


def _request_id():
    """Server-generated unique request id that starts with 'req_' (PRD §2.2)."""
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        # api_request_timestamp is server-generated wall-clock ISO 8601 UTC with
        # three fractional digits — this is the request stamp, NOT the logical
        # clock (PRD §2.2).
        "api_request_timestamp": format_iso8601_millis(
            datetime.datetime.now(datetime.timezone.utc)
        ),
    }
    if extra:
        meta.update(extra)
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
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": has_more,
            }
        ),
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
