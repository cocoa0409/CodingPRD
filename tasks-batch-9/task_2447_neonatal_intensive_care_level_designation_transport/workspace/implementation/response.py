"""Response envelope (PRD 2.2, 2.3)."""
import random
import string
from decimal import Decimal

from flask import jsonify

import clock

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.wall_now_fmt(),
    }
    if extra:
        meta.update(extra)
    return meta


def clean(value):
    """JSON-safe conversion: Decimal -> float, datetime -> ISO-8601 string."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return dict((k, clean(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": clean(data) if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, total_count):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(rows)) < total_count,
        }),
        "response_type": "array",
        "data": [clean(r) for r in rows],
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
