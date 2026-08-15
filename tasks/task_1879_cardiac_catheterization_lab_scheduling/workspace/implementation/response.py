"""Standard response envelope helpers (PRD section 2.2)."""
import uuid

from flask import jsonify

from db import tick
from helpers import fmt_ms


def _meta(pagination=None):
    m = {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_ms(tick()),
    }
    if pagination:
        m.update(pagination)
    return m


def success(data, status=200, is_list=False, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if is_list else "object",
        "data": data,
    }
    return jsonify(body), status


def error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
