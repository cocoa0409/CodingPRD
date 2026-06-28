"""Response envelope helpers (SCAFFOLD.yaml §1.0 / PRD §2.2).

Success: { "meta": {api_request_id, api_request_timestamp[, pagination]},
           "response_type": "object"|"array", "data": {...} }
Error:   { "meta": {...}, "response_type": "error",
           "data": {"error_id": ..., "message": ...} }
"""

import datetime
import random
import string

from flask import jsonify

from db import iso_millis


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        # The request timestamp is a real server clock stamp (per PRD it is a
        # server-generated ISO-8601 UTC timestamp with three fractional digits).
        "api_request_timestamp": iso_millis(
            datetime.datetime.now(datetime.timezone.utc)
        ),
    }
    if extra:
        m.update(extra)
    return m


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def array_response(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }
    )
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
