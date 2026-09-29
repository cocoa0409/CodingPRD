"""Standard response envelope (PRD section 2.2) and list serialization."""

import random
import string
from datetime import date, datetime
from decimal import Decimal

from flask import jsonify

import clock

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.fmt_datetime(clock.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def _val(value):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, datetime):
        return clock.fmt_datetime(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_val(v) for v in value]
    if isinstance(value, tuple):
        return [_val(v) for v in value]
    if isinstance(value, dict):
        return dump(value)
    return value


def dump(entity):
    """Public projection of a stored entity: private keys (_x) are dropped."""
    out = {}
    for key, value in entity.items():
        if key.startswith("_"):
            continue
        out[key] = _val(value)
    return out


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": _val(data)}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def collection(rows, limit, offset, total_count):
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(rows) < total_count,
    }
    body = {
        "meta": _meta(meta),
        "response_type": "array",
        "data": [_val(r) for r in rows],
    }
    return jsonify(body), 200


def error(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
