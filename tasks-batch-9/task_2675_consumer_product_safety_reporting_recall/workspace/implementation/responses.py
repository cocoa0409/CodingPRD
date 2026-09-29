"""Standard response envelope helpers (PRD section 2.2 / 2.3)."""

import random
import string

from flask import jsonify

import store

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": store.iso(store.wall_now()),
    }


def object_response(row, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": store.serialize(row) if row is not None else {},
    }
    return jsonify(body), status


def created(row):
    return object_response(row, 201)


def list_response(rows, limit, offset):
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
        "data": [store.serialize(r) for r in page],
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
