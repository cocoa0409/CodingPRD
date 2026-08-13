"""Standard response envelope helpers (PRD section 2.2)."""

import secrets
import string

from flask import jsonify

from db import store


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def success(data, response_type="object", code=200, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), code


def error_response(api_error):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": store.now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.http_status
