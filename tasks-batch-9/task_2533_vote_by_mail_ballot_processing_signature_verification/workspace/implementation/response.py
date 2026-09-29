"""Response envelope helpers -- PRD 2.2 / 2.3."""
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

import db

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    stamp = datetime.now(timezone.utc)
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": stamp.strftime("%Y-%m-%dT%H:%M:%S.")
        + "%03dZ" % (stamp.microsecond // 1000),
    }


def serialize(rec):
    """Public projection of a stored record: private keys dropped, datetimes canonicalised."""
    if rec is None:
        return None
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        out[key] = serialize_value(value)
    return out


def serialize_value(value):
    if isinstance(value, datetime):
        return db.iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [serialize_value(v) for v in value]
    return value


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": serialize_value(data) or {}}
    return jsonify(body), status


def record_response(rec, status=200):
    return object_response(serialize(rec), status)


def list_response(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(window) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in window],
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
