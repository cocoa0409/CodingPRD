"""Response envelope helpers (PRD 2.2, 2.3)."""

import random
import string
from decimal import Decimal

from flask import jsonify

import clock

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.wall_iso(),
    }


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def serialize(row):
    if row is None:
        return {}
    return {k: jsonable(v) for k, v in row.items() if not k.startswith("_")}


def ok(row, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialize(row) if isinstance(row, dict) else jsonable(row),
    }
    return jsonify(body), status


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) if isinstance(r, dict) else jsonable(r) for r in rows],
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
