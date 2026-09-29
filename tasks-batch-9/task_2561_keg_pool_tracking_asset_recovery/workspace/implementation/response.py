"""Response envelope helpers.

Success:
  { "meta": {"api_request_id", "api_request_timestamp"[, pagination]},
    "response_type": "object"|"array", "data": ... }
Error:
  { "meta": {...}, "response_type": "error",
    "data": {"error_id", "message"} }
"""
import random
import string
from datetime import date, datetime
from decimal import Decimal

from flask import jsonify

import clock
import util

_ALPHANUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": util.iso(clock.now()),
    }


# PRD 2.4: created_at/updated_at carry three fractional digits.  Every other
# instant is rendered the way the PRD writes them (2026-08-01T00:00:00Z).
_MILLIS_FIELDS = ("created_at", "updated_at")


def _clean(value, key=None):
    if isinstance(value, datetime):
        if key in _MILLIS_FIELDS or isinstance(value, util.MillisInstant):
            return util.iso(value)
        return util.iso_instant(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _clean(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v, key) for v in value]
    return value


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _clean(data if data is not None else {}),
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
    body = {"meta": meta, "response_type": "array", "data": _clean(list(rows))}
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
