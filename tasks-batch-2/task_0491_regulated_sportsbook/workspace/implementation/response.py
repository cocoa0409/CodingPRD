"""Standard response envelope helpers (PRD §2.2).

Success: { "meta": {api_request_id, api_request_timestamp[, pagination]},
           "response_type": "object"|"array", "data": {...} | [...] }
Error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error",
           "data": { "error_id": "...", "message": "..." } }

api_request_timestamp is an ISO 8601 UTC timestamp with three fractional digits
(PRD §2.2). It reflects the logical clock so timestamps stay consistent with the
clock that drives all time-dependent behavior.
"""

import random
import string

from flask import jsonify

from db import iso_now

_ALNUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(random.choices(_ALNUM, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_now(),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status=200, pagination=None):
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
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
