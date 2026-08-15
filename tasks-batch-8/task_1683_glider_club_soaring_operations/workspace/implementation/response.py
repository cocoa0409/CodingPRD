"""Standard response envelope helpers per PRD section 2.2."""

import uuid

from flask import jsonify

from db import now
from util import fmt_ts


def _request_id():
    return "req_" + uuid.uuid4().hex[:20]


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(now()),
    }


def success(data, response_type="object", status=200, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(error_id, message, status):
    return jsonify(error_body(error_id, message)), status
