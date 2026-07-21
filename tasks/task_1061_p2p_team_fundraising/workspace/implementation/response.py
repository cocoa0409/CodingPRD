"""Standard response envelope (PRD 2.2)."""
import random
import string

from flask import jsonify

import db

_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": db.now_iso(),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def list_response(rows, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), status


def object_response_paginated(data, limit, offset, total_count, status=200):
    """Object-shaped payload that still reports pagination in meta."""
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {"meta": meta, "response_type": "object", "data": data}
    return jsonify(body), status


def paged(records, serializer, limit, offset):
    """PRD 2.3: created_at ascending, total_count before the window."""
    rows = db.ordered(records)
    total_count = len(rows)
    window = rows[offset:offset + limit]
    return list_response(
        [serializer(r) for r in window], limit, offset, total_count
    )


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
