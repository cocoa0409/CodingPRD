"""Standard response envelope helpers (PRD section 2.2 / 2.3)."""
import secrets

from flask import jsonify

import db


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": db.now_iso(),
    }


def success(data, status=200, pagination=None):
    meta = _meta()
    response_type = "object"
    if pagination is not None:
        meta.update(pagination)
        response_type = "array"
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def error(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
