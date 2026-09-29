"""Response envelope helpers (PRD 2.2)."""

import json
import random
import string
from decimal import Decimal

from flask import Response

import db

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_iso(),
    }


def clean(value):
    """Strip internal keys and make the value JSON-serialisable."""
    if isinstance(value, dict):
        return dict(
            (k, clean(v)) for k, v in value.items() if not str(k).startswith("_")
        )
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    return value


def _emit(payload, status):
    body = json.dumps(payload, ensure_ascii=False)
    return Response(body, status=status, mimetype="application/json")


def object_response(data, status=200):
    payload = {
        "meta": _meta(),
        "response_type": "object",
        "data": clean(data),
    }
    return _emit(payload, status)


def list_response(rows, limit, offset, total_count, status=200):
    page = clean(list(rows))
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(page)) < total_count
    payload = {
        "meta": meta,
        "response_type": "array",
        "data": page,
    }
    return _emit(payload, status)


def array_response(rows, status=200):
    """Non-paginated array payload (bulk creation results)."""
    payload = {
        "meta": _meta(),
        "response_type": "array",
        "data": clean(list(rows)),
    }
    return _emit(payload, status)


def error_response(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _emit(payload, status)
