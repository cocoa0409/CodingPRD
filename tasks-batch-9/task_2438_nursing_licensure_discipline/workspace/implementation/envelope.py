"""Response envelope helpers (PRD 2.2)."""
import random
import string
from datetime import datetime
from decimal import Decimal

from flask import g, jsonify

import store
from timeutil import iso

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def to_json(value):
    if isinstance(value, dict):
        return dict((k, to_json(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [to_json(v) for v in value]
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(store.STORE.clock),
    }


def touched():
    if not hasattr(g, "_touched_ids"):
        g._touched_ids = set()
    return g._touched_ids


def mark_new(record):
    """A record created in this request is already at version 1 -- no bump."""
    touched().add(id(record))
    return record


def touch(record):
    """Refresh updated_at and advance version once per record per request."""
    seen = touched()
    if id(record) in seen:
        record["updated_at"] = store.STORE.clock
        return record
    seen.add(id(record))
    record["updated_at"] = store.STORE.clock
    record["version"] = record.get("version", 1) + 1
    return record


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": to_json(data)}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    body = {"meta": meta, "response_type": "array", "data": to_json(items)}
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
