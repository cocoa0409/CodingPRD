"""Standard response envelope (PRD section 2.2 / scaffold response_envelope)."""
import secrets

from flask import jsonify

from util import iso_millis, wall_now


def _meta(pagination=None):
    m = {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": iso_millis(wall_now()),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def success(data, status=200, pagination=None):
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
