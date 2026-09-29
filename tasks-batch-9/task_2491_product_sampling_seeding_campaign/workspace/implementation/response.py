"""Response envelope helpers (PRD 2.2 / scaffold response_envelope)."""

import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if extra:
        m.update(extra)
    return m


def single(data, http_status=200):
    body = {
        "meta": meta(),
        "response_type": "object",
        "data": jsonable(data),
    }
    return jsonify(body), http_status


def collection(rows, total_count, limit, offset):
    body = {
        "meta": meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(rows)) < total_count,
        }),
        "response_type": "array",
        "data": [jsonable(r) for r in rows],
    }
    return jsonify(body), 200


def failure(error_id, message, http_status):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
