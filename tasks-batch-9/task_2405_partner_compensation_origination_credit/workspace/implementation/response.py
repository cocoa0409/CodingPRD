"""Response envelope helpers (PRD 2.2, 2.3)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

from db import serialize

ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def _timestamp():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()}


def ok(entity, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialize(entity) if entity is not None else {},
    }
    return jsonify(body), status


def created(entity):
    return ok(entity, 201)


def raw_ok(data):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), 200


def listing(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in page],
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
