"""Response envelope helpers (PRD §2.2, §2.3)."""

import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

from db import store

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def _scalar(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (list, tuple)):
        return [_scalar(v) for v in value]
    if isinstance(value, dict):
        return {k: _scalar(v) for k, v in value.items()}
    return value


def serialize(row):
    if row is None:
        return None
    return {k: _scalar(v) for k, v in row.items() if not k.startswith("_")}


def _meta(pagination=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(store.now()),
    }
    if pagination:
        meta.update(pagination)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": serialize(data) if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def empty_ok():
    body = {"meta": _meta(), "response_type": "object", "data": {}}
    return jsonify(body), 200


def listing(rows, pagination):
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": [serialize(r) for r in rows],
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
