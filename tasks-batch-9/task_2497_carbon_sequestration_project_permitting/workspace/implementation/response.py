"""Response envelope helpers (PRD Section 2.2 / 2.3)."""

import json
import random
import string
from decimal import Decimal

from flask import Response

import clock

_ID_ALPHABET = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ID_ALPHABET) for _ in range(20))


def _jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.now_iso(),
    }


def _emit(payload, http_status):
    body = json.dumps(_jsonable(payload), allow_nan=False)
    return Response(body, status=http_status, mimetype="application/json")


def object_response(data, http_status=200):
    return _emit(
        {"meta": _base_meta(), "response_type": "object", "data": data},
        http_status,
    )


def list_response(items, limit, offset, total_count, http_status=200):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return _emit(
        {"meta": meta, "response_type": "array", "data": items},
        http_status,
    )


def error_response(error_id, message, http_status):
    return _emit(
        {
            "meta": _base_meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        },
        http_status,
    )
