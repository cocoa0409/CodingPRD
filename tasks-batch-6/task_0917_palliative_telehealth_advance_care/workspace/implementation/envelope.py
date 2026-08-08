"""Response envelope helpers (PRD 2.2) and row serialisation."""

import random
import string
from datetime import datetime
from decimal import Decimal

from flask import jsonify

from store import fmt_dt, store

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(store.now()),
    }


def serialise(value):
    """Render a stored value for JSON: datetimes canonicalised, Decimals as
    numbers, private keys (leading underscore) stripped."""
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: serialise(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [serialise(v) for v in value]
    return value


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialise(data) if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialise(r) for r in rows],
    }
    return jsonify(body), 200


def error_body(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
