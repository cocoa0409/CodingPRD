"""Standard response envelope helpers (PRD §2.2, scaffold response_envelope).

success: { "meta": { "api_request_id", "api_request_timestamp", [pagination] },
           "response_type": "object"|"array", "data": {...} }
error:   { "meta": {...}, "response_type": "error",
           "data": { "error_id", "message" } }
"""
import random
import string

from flask import jsonify

from db import db


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, pagination=None):
    rtype = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(pagination),
        "response_type": rtype,
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def error_response(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body
