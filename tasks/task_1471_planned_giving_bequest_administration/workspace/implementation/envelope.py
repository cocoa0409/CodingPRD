"""Response envelope helpers (PRD 2.2 / scaffold response_envelope)."""
import random
import string

from flask import jsonify

import store


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {
        "api_request_id": _req_id(),
        "api_request_timestamp": store.iso(store.now()),
    }


def success(data, code=200, pagination=None):
    m = _meta()
    if pagination is not None:
        m.update(pagination)
    body = {
        "meta": m,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = code
    return resp


def error_response(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
