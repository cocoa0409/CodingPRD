"""Response envelope of PRD 2.2 and pagination of PRD 2.3."""

import random
import string

from flask import jsonify, request

import db
from errors import ApiError, fail

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_iso(),
    }


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def array_response(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(exc):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    return jsonify(body), exc.http_status


def _int_param(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %d" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %d" % (name, maximum))
    return value


def pagination():
    limit = _int_param("limit", PAGINATION_LIMIT_DEFAULT,
                       PAGINATION_LIMIT_MIN, PAGINATION_LIMIT_MAX)
    offset = _int_param("offset", PAGINATION_OFFSET_DEFAULT,
                        PAGINATION_OFFSET_MIN)
    return limit, offset


def paginated(rows, serializer):
    """Apply pagination to an already-sorted row list."""
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return array_response([serializer(r) for r in page], limit, offset, total)


__all__ = [
    "object_response", "array_response", "error_response", "paginated",
    "pagination", "ApiError",
]
