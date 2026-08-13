"""Standard response envelope (PRD section 2.2)."""
import random
import string

from flask import jsonify

import db
from util import fmt_dt


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))


def success(data, response_type="object", status=200, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(db.now()),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": fmt_dt(db.now()),
        },
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
