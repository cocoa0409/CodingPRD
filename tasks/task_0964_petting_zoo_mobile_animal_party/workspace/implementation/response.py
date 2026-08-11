"""Standard response envelope helpers (PRD §2.2)."""
from flask import jsonify

from util import fmt_dt, new_req_id, wall_now


def _meta(pagination=None):
    meta = {
        "api_request_id": new_req_id(),
        "api_request_timestamp": fmt_dt(wall_now()),
    }
    if pagination:
        meta.update(pagination)
    return meta


def ok(data, status=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
