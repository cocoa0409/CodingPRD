"""Response envelope helpers (PRD section 2.2, SCAFFOLD response_envelope)."""

import random
import string
from decimal import Decimal

from flask import jsonify

from db import db

_ALNUM = string.ascii_uppercase + string.digits


def new_api_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": new_api_request_id(),
        "api_request_timestamp": db.now_iso(),
    }


def jsonable(value):
    """Strip internal keys and render Decimals as JSON numbers."""
    if isinstance(value, Decimal):
        as_float = float(value)
        return int(as_float) if value == value.to_integral_value() and value.as_tuple().exponent == 0 else as_float
    if isinstance(value, dict):
        return dict(
            (key, jsonable(inner))
            for key, inner in value.items()
            if not key.startswith("_")
        )
    if isinstance(value, (list, tuple)):
        return [jsonable(inner) for inner in value]
    return value


def object_response(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": jsonable(data if data is not None else {}),
    }
    return jsonify(body), status


def list_response(rows, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": jsonable(list(rows))}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
