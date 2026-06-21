"""Standard response envelope helpers (PRD §2.2).

Success:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "...Z",
              [pagination fields for lists] },
    "response_type": "object" | "array",
    "data": {...} | [...] }

Error:
  { "meta": { "api_request_id": ..., "api_request_timestamp": ... },
    "response_type": "error",
    "data": { "error_id": "...", "message": "..." } }
"""

import random
import string

from flask import jsonify

from timeutil import format_iso, now_utc

_ALNUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(random.choices(_ALNUM, k=20))


def _base_meta():
    # api_request_timestamp is server wall-clock (a real timestamp on the
    # response), independent of the test-controllable SystemClock.
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": format_iso(now_utc()),
    }


def object_response(data, status=200):
    body = {"meta": _base_meta(), "response_type": "object", "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def array_response(items, limit, offset, total_count, status=200):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
