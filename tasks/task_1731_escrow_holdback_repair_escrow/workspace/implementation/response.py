"""Standard response envelope helpers (PRD section 2.2)."""

import random
import string

from flask import jsonify

from db import now_iso


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def success(data, response_type="object", status=200, pagination=None):
    meta = {"api_request_id": _req_id(), "api_request_timestamp": now_iso()}
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error_response(error_id, message, http_status):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": now_iso()},
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
