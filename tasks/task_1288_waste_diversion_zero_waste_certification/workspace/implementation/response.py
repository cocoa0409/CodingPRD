"""Standard response envelope helpers (SCAFFOLD §1.0 / PRD §2.2)."""

import random
import string

from flask import jsonify

from db import now_ts
from errors import ApiError


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=22))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_ts()}


def success_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def success_list(items, pagination):
    meta = _meta()
    meta.update(pagination)
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
