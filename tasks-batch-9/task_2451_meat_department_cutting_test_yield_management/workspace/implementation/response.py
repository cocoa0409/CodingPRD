"""Response envelope helpers (PRD §2.2, §2.3)."""

import random
import string
from decimal import Decimal

from flask import jsonify

from db import flush, now_iso

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }


def jsonable(value):
    if isinstance(value, Decimal):
        as_float = float(value)
        if as_float == 0.0:
            return 0.0          # normalise a negative zero away
        return as_float
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def public(entity):
    """Strip private bookkeeping keys and make the payload JSON-safe."""
    out = {}
    for key, value in entity.items():
        if key.startswith("_"):
            continue
        out[key] = jsonable(value)
    return out


def object_response(entity, status=200):
    flush()
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": public(entity),
    }
    return jsonify(body), status


def data_response(data, status=200):
    flush()
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": jsonable(data),
    }
    return jsonify(body), status


def list_response(rows, limit, offset):
    flush()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [public(row) for row in page],
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
