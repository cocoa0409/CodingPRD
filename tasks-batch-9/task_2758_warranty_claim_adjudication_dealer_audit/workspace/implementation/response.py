"""Response envelope helpers (PRD 2.2 / 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

import db

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    # The envelope timestamp is a real server-generated instant (it is not a
    # deadline evaluation, which PRD 2.6 reserves for the logical clock).
    stamp = datetime.now(timezone.utc).replace(tzinfo=None)
    return {"api_request_id": _request_id(), "api_request_timestamp": db.iso3(stamp)}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": db.public(data) if isinstance(data, dict) else data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def raw(data, status=200):
    """2xx with a plain (already public) dict payload."""
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def listing(rows, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(rows) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [db.public(row) for row in rows],
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
