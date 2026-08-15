"""PRD 2.2 response envelope helpers."""
from flask import jsonify

from db import wall_now
from util import fmt_dt, request_id


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(wall_now()),
    }


def ok_object(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_list(items, pagination):
    meta = _meta()
    meta.update(pagination)
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(error_id, message, status):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status
