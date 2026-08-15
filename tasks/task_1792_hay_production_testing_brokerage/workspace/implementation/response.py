"""Standard response envelope helpers (field names fixed by the scaffold)."""

import random
import string

from flask import jsonify

from db import now_ts


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def success(data, response_type="object", code=200, pagination=None):
    meta = {"api_request_id": _req_id(), "api_request_timestamp": now_ts()}
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), code


def error(error_id, message, status):
    meta = {"api_request_id": _req_id(), "api_request_timestamp": now_ts()}
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
