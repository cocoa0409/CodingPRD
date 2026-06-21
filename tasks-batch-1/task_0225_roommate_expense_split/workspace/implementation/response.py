"""Standard response envelope helpers (PRD §2.2, scaffold response_envelope)."""
import random
import string

from flask import jsonify

import clock
from db import db


def _request_id():
    rnd = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + rnd


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.format_iso8601(db.now()),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, status=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
