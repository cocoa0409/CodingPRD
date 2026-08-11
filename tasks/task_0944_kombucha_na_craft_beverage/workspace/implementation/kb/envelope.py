"""Response envelope (PRD 2.2) and record serialisation."""

import random
import string
from datetime import datetime
from decimal import Decimal

from flask import jsonify

from .store import db
from .util import render_instant

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": render_instant(db.clock),
    }


def render_value(value):
    """Convert stored values into JSON-safe ones.

    datetime -> canonical ISO 8601 with three fractional digits,
    Decimal  -> JSON number,
    dict/list -> recursively rendered, private ``_`` keys dropped.
    """
    if isinstance(value, datetime):
        return render_instant(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: render_value(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [render_value(v) for v in value]
    return value


def serialize(record):
    if record is None:
        return None
    return {k: render_value(v) for k, v in record.items() if not k.startswith("_")}


def object_response(record, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialize(record) if record is not None else {},
    }
    return jsonify(body), status


def raw_object_response(payload, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": render_value(payload)}
    return jsonify(body), status


def list_response(records, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(records)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in records],
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
