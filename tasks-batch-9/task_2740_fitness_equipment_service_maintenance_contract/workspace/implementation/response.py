"""Response envelope helpers.

Success : {"meta": {...}, "response_type": "object"|"array", "data": ...}
Error   : {"meta": {...}, "response_type": "error",
           "data": {"error_id": ..., "message": ...}}
"""
from decimal import Decimal

from flask import jsonify, request

import db
from errors import ApiError

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _meta():
    return {
        "api_request_id": db.request_id(),
        "api_request_timestamp": db.now_iso(),
    }


def scrub(value):
    """Serialise stored values: Decimals become JSON numbers, privates dropped."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    return value


def object_response(payload, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": scrub(payload) if payload is not None else {},
    }
    return jsonify(body), status


def created_response(payload):
    return object_response(payload, 201)


def array_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [scrub(r) for r in rows],
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    try:
        value = int(text)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s is below the permitted minimum" % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s is above the permitted maximum" % name)
    return value


def pagination():
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def paginated(rows):
    """Apply the declared pagination window to an ordered row list."""
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    return array_response(window, limit, offset, total)


def listing(collection, filters=None, predicate=None):
    """Default listing: conjunctive equality filters, created_at ascending."""
    rows = db.ordered(collection, predicate)
    if filters:
        for field, expected in filters.items():
            if expected is None:
                continue
            rows = [r for r in rows if r.get(field) == expected]
    return paginated(rows)


def bool_filter(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    text = raw.strip().lower()
    if text in ("true", "1"):
        return True
    if text in ("false", "0"):
        return False
    raise ApiError("ERR_INVALID_REQUEST", "%s must be a boolean" % name)


def arg(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
