"""Response envelope helpers (PRD 2.2, SCAFFOLD response_envelope)."""

import random
import string
from decimal import Decimal

from flask import jsonify

from errors import ApiError
from store import store

_ALNUM = string.ascii_uppercase + string.digits

# Fields kept only for internal bookkeeping never leave the process.
_INTERNAL_PREFIX = "_"


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": store.now_iso(),
    }


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith(_INTERNAL_PREFIX)}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def serialize(record):
    return jsonable(record)


def ok(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": serialize(data),
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def collection(records, limit, offset, total):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + limit) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in records],
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(exc):
    return jsonify(error_body(exc.error_id, exc.message)), exc.http_status


def fail(error_id, message=None):
    raise ApiError(error_id, message)
