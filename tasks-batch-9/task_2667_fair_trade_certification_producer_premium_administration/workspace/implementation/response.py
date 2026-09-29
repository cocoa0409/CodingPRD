"""Response envelope helpers (PRD 2.2 / 2.3)."""
from decimal import Decimal

from flask import jsonify

from common import (PAGE_LIMIT_DEFAULT, next_seq, now_iso, request_id)


def _plain(value):
    if isinstance(value, Decimal):
        as_int = value.to_integral_value()
        if value == as_int and -value.as_tuple().exponent == 0:
            return int(as_int)
        return float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def jsonable(value):
    return _plain(value)


def _meta(extra=None):
    meta = {"api_request_id": request_id(), "api_request_timestamp": now_iso()}
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": jsonable(data or {})}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, total):
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(rows) < total,
    }
    body = {
        "meta": _meta(page),
        "response_type": "array",
        "data": [jsonable(r) for r in rows],
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
