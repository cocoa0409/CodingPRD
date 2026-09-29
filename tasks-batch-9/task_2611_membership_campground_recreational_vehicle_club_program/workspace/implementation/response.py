"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string

from flask import jsonify, request

import clock
from errors import fail

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.now_iso(),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def pagination_args():
    """limit defaults to 10, min 1, max 100; offset defaults to 0, min 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(str(limit_raw).strip())
        except Exception:
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(str(offset_raw).strip())
        except Exception:
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must not be negative")
    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination_args()
    total = len(rows)
    window = rows[offset:offset + limit]
    return listing([serializer(r) for r in window], limit, offset, total)
