"""Response envelope helpers, matching PRD section 2.2 exactly."""

import random
import string
from flask import jsonify
from store import now
from domain_time import fmt


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def success(data, status=200, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt(now()),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": fmt(now()),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
