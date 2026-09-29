"""Response envelopes (PRD 2.2)."""

import random
import string

from flask import jsonify

import db
import serialize
from util import iso

_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    suffix = "".join(random.choice(_ALNUM) for _ in range(20))
    return {
        "api_request_id": "req_" + suffix,
        "api_request_timestamp": iso(db.now()),
    }


def ok(data, status=200):
    """Single-object envelope."""
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def entity(row, status=200):
    """Flush the once-per-request Domain.version bumps, then serialise."""
    db.finalize()
    return ok(serialize.one(row), status)


def created(row):
    return entity(row, 201)


def collection(rows, limit, offset):
    db.finalize()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array", "data": serialize.many(page)}
    return jsonify(body), 200


def failure(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
