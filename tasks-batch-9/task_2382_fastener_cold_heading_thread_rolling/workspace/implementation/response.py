"""Response envelope helpers (PRD 2.2)."""

import json
import random
import string
from decimal import Decimal

from flask import Response

from db import db, public

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_iso(),
    }
    if pagination:
        meta.update(pagination)
    return meta


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def _emit(body, status):
    return Response(
        json.dumps(jsonable(body), allow_nan=False),
        status=status,
        mimetype="application/json",
    )


def ok(data=None, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": public(data) if isinstance(data, dict) else (data if data is not None else {}),
    }
    if body["data"] is None:
        body["data"] = {}
    return _emit(body, status)


def created(data):
    return ok(data, 201)


def ok_list(records, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(records) < total_count,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": [public(r) for r in records],
    }
    return _emit(body, 200)


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return _emit(body, err.http_status)
