"""Standard response envelope (PRD section 2.2)."""
import uuid
from flask import jsonify

import db


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": db.now_iso(),
    }


def success(data, status=200, pagination=None):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), status


def error(api_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    return jsonify(body), api_err.http_status
