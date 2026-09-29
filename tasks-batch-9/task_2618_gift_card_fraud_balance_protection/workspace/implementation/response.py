"""Response envelope helpers (PRD 2.2 / 2.3)."""
import random
import string
from datetime import datetime

from flask import jsonify

import clock

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.fmt(clock.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def serialize(value):
    if isinstance(value, datetime):
        return clock.fmt(value)
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    return value


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialize(data),
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def collection(rows, limit, offset, total_count):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(rows) < total_count,
        }),
        "response_type": "array",
        "data": [serialize(r) for r in rows],
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
