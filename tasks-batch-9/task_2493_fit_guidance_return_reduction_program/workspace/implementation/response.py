"""The response envelope defined by PRD 2.2 and SCAFFOLD response_envelope."""

import random
import string
from datetime import datetime

from flask import jsonify

import clock

_ALPHANUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.now_iso(),
    }


def serialize(value):
    """Render a stored row/value as JSON-safe data.

    Internal bookkeeping keys (``_seq`` etc.) never leave the server, and
    datetimes are rendered in the PRD's three-fractional-digit UTC format.
    """
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if isinstance(key, str) and key.startswith("_"):
                continue
            out[key] = serialize(item)
        return out
    if isinstance(value, list):
        return [serialize(item) for item in value]
    if isinstance(value, tuple):
        return [serialize(item) for item in value]
    if isinstance(value, datetime):
        return clock.iso(value)
    return value


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialize(data) if data is not None else {},
    }
    return jsonify(body), status


def array_response(rows, pagination=None, status=200):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(row) for row in rows],
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
