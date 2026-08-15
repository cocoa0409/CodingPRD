"""Standard response envelope helpers (PRD section 2.2)."""

from flask import jsonify

import db
from util import fmt_ts, request_id


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_ts(db.now_wall()),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, response_type="object", pagination=None):
    payload = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(payload), status


def success_list(items, pagination):
    return success(items, status=200, response_type="array", pagination=pagination)


def error(error_id, status, message):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(payload), status
