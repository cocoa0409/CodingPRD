"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""
import json
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import Response

import store

_ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": store.fmt_dt(store.now()),
    }


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return store.fmt_dt(value)
    if isinstance(value, dict):
        return dict((k, jsonable(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def _emit(body, status):
    return Response(
        json.dumps(jsonable(body)),
        status=status,
        mimetype="application/json",
    )


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return _emit(body, status)


def created(data):
    return ok(data, 201)


def ok_list(rows, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return _emit(body, 200)


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _emit(body, http_status)


def paginate(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, total
