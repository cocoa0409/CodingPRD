import random
import string
from flask import jsonify

from db import db, fmt_dt


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(db.now()),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status=200, is_array=False, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if is_array else "object",
        "data": data,
    }
    return jsonify(body), status


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
