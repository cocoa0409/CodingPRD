"""Response envelope construction (PRD 2.2, 2.3)."""

import random
import string

from flask import jsonify

from store import fmt_ts, now

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(now()),
    }


def object_response(data, status=200):
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }), status


def created(data):
    return object_response(data, 201)


def empty_response():
    return object_response({}, 200)


def list_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return jsonify({
        "meta": meta,
        "response_type": "array",
        "data": rows,
    }), 200


def error_response(error_id, message, status):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
