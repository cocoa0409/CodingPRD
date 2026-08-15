"""Standard response envelope helpers (PRD section 2.2).

Success: {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}
"""

import uuid

from flask import jsonify

import clock


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": clock.iso3(clock.now()),
    }


def success(data, response_type="object", status=200, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
