"""Response envelope helpers (PRD 2.2, 2.3)."""
from datetime import datetime
from decimal import Decimal
from fractions import Fraction

from flask import jsonify

import clock
from util import fmt_dt, new_request_id

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_dt(clock.now()),
    }


def jsonable(value):
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Fraction):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    return value


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": jsonable(data)}
    return jsonify(body), status


def created_response(data):
    return object_response(data, 201)


def array_response(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": jsonable(list(items))}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
