"""Response envelope helpers (PRD 2.2 / scaffold response_envelope)."""

import random
import string
from datetime import date, datetime
from decimal import Decimal

from flask import jsonify

import db
from timeutil import iso

_ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def api_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": api_request_id(),
        "api_request_timestamp": iso(db.now()),
    }


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def public(row):
    """Serialise a stored row, dropping private bookkeeping keys."""
    if row is None:
        return None
    return {k: jsonable(v) for k, v in row.items() if not k.startswith("_")}


def ok(data=None, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": {} if data is None else jsonable(data),
    }
    return jsonify(body), status


def created(data=None):
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
        "data": [jsonable(r) for r in rows],
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
