"""Standard response envelope (PRD 2.2)."""
import random
import string

from flask import jsonify

import clock

_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": clock.fmt(clock.now()),
    }


def object_response(data, status=200):
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }), status


def created(data):
    return object_response(data, 201)


def list_response(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({
        "meta": meta,
        "response_type": "array",
        "data": items,
    }), 200


def page(rows, serializer, limit, offset):
    """Slice an already-ordered row list into one page of serialised objects."""
    total = len(rows)
    window = rows[offset:offset + limit]
    return list_response([serializer(row) for row in window], limit, offset, total)


def error_response(error_id, message, status):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status
