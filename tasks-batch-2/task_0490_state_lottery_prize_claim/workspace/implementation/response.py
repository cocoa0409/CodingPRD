"""Standard response envelope helpers (PRD section 2.2)."""
from flask import jsonify

from util import new_request_id, now_ts


def _meta(extra=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_ts(None),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status=200, pagination=None):
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
