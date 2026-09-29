"""Response envelope helpers (PRD 2.2)."""

import random
import string
from decimal import Decimal

from flask import jsonify

from db import now_ts

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _convert(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _convert(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_convert(v) for v in value]
    return value


def public(record):
    """Strip internal bookkeeping keys and normalise numeric types."""
    return _convert(record)


def _meta(extra=None):
    meta = {"api_request_id": request_id(), "api_request_timestamp": now_ts()}
    if extra:
        meta.update(extra)
    return meta


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": public(data or {})}
    return jsonify(body), code


def created(data):
    return ok(data, 201)


def listing(items, total_count, limit, offset):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": [public(i) for i in items],
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
