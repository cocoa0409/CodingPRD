"""Response envelope helpers (PRD 2.2, 2.3)."""

import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

import derive
from timeutil import Instant, fmt_ms

_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": fmt_ms(datetime.now(timezone.utc)),
    }


def jsonable(value):
    if isinstance(value, Instant):
        return value.raw
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def ok(data, status=200):
    derive.flush_field_versions()
    body = {"meta": _meta(), "response_type": "object", "data": jsonable(data)}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    derive.flush_field_versions()
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": [jsonable(r) for r in rows]}
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
