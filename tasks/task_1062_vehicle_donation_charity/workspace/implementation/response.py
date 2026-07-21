"""Response envelope helpers (PRD section 2.2) and record serialisation."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

import db

_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    rid = "req_" + "".join(random.choice(_ALNUM) for _ in range(20))
    real = datetime.now(timezone.utc)
    stamp = real.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(
        real.microsecond // 1000
    )
    return {"api_request_id": rid, "api_request_timestamp": stamp}


def _clean(value):
    if isinstance(value, datetime):
        return db.fmt_dt(value)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def serialize(rec):
    return _clean(rec)


def ok(data, status=200):
    meta = _meta()
    body = {
        "meta": meta,
        "response_type": "object",
        "data": serialize(data) if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset):
    """Apply pagination to an already-ordered, already-filtered row list."""
    total = len(rows)
    page = rows[offset : offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(page) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in page],
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
