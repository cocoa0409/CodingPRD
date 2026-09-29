"""Response envelope helpers (PRD 2.2 / 2.3)."""

import uuid

from flask import jsonify, request

from db import db, iso, public

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": iso(db.now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data or {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_arg(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def page_params():
    limit = _int_arg("limit", LIMIT_DEFAULT)
    offset = _int_arg("offset", OFFSET_DEFAULT)
    if limit < LIMIT_MIN:
        limit = LIMIT_MIN
    if limit > LIMIT_MAX:
        limit = LIMIT_MAX
    if offset < 0:
        offset = OFFSET_DEFAULT
    return limit, offset


def paginated(records, serializer=public):
    limit, offset = page_params()
    total = len(records)
    window = records[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(window) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(r) for r in window],
    }
    return jsonify(body), 200
