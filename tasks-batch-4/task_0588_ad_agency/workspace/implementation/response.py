"""Standard response envelope (PRD 2.2)."""
import random
import string

from flask import jsonify

import db

_ALPHANUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20)),
        "api_request_timestamp": db.iso_now(),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset):
    """rows: the full filtered result set (already ordered). Paginates it."""
    total = len(rows)
    window = rows[offset: offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(window) < total
    body = {"meta": meta, "response_type": "array", "data": [db.public(r) for r in window]}
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
