"""Standard response envelope helpers (PRD 2.2, scaffold response_envelope).

Success: { "meta": { api_request_id, api_request_timestamp[, pagination] },
           "response_type": "object"|"array", "data": {} }
Error:   { "meta": {...}, "response_type": "error",
           "data": { "error_id", "message" } }
"""
import random
import string
from datetime import timezone

from flask import jsonify

import clock
from timeutil import iso_now


def _request_id():
    return "req_" + "".join(
        random.choices(string.ascii_letters + string.digits, k=20)
    )


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_now(clock.now().astimezone(timezone.utc)),
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


def error(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
