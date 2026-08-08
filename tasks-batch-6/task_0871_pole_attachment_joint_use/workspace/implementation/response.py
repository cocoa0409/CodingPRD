"""Standard response envelope helpers (verbatim from PRD 2.2)."""

import random
import string

from flask import jsonify

from clock import LOGICAL_CLOCK, render_datetime


def _request_id():
    body = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + body


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": render_datetime(LOGICAL_CLOCK.now()),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def object_response(data, status=200):
    payload = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(payload), status


def array_response(items, limit, offset, total, status=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(items)) < total,
    }
    payload = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(payload), status


def error_response(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(payload), status
