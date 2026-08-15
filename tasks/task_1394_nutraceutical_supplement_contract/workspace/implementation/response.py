"""Response envelope helpers (PRD section 2.2).

Success: {"meta": {"api_request_id", "api_request_timestamp"[, pagination]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}
"""
import random
import string

from flask import jsonify

from db import now_iso


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def ok(data, status=200, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
        response_type = "array"
    else:
        response_type = "object"
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error(error_id, http_status, message):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
