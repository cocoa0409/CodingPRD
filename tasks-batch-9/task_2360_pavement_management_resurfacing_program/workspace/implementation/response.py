"""Standard response envelope (PRD 2.2)."""
import random
import string
from datetime import datetime

from flask import jsonify

import clock

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.iso(clock.now()),
    }


def _plain(value):
    if isinstance(value, datetime):
        return clock.iso(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _plain(data) if data is not None else {},
    }
    return jsonify(body), status


def array_response(items, status=200, pagination=None):
    meta = _meta()
    if pagination:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [_plain(i) for i in items],
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
