"""Response envelope helpers (PRD section 2.2 / SCAFFOLD response_envelope)."""

import random
import string

from flask import jsonify, request

import db
from errors import ApiError

ALNUM = string.ascii_letters + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_ts(),
    }


def object_response(data, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def created(data):
    return object_response(data, 201)


def error_response(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def pagination_params():
    """Read and validate the limit/offset query parameters."""
    args = request.args
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if "limit" in args:
        raw = args.get("limit")
        limit = _positive_int(raw, "limit")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "limit must be between %d and %d." % (LIMIT_MIN, LIMIT_MAX),
            )
    if "offset" in args:
        raw = args.get("offset")
        offset = _positive_int(raw, "offset")
        if offset < OFFSET_MIN:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


def _positive_int(raw, name):
    if raw is None or raw == "":
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)


def list_response(rows, serializer, status=200):
    """Paginate an already-ordered list of rows and wrap it in the envelope."""
    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(r) for r in page],
    }
    return jsonify(body), status
