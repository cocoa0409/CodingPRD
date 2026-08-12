"""Standard response envelope helpers (PRD section 2.2)."""

import uuid

from flask import jsonify

import clock
import db
from util import paginate


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": clock.fmt(clock.now()),
    }


def success(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": db.public(data) if isinstance(data, dict) else data}
    return jsonify(body), status


def success_raw(data, status=200):
    """data is already a plain dict/list (no internal fields to strip)."""
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def list_response(items):
    page, page_meta = paginate(items)
    meta = _meta()
    meta.update(page_meta)
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [db.public(e) for e in page],
    }
    return jsonify(body), 200


def error_response(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
