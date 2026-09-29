"""Response envelope helpers (§2.2) and pagination (§2.3)."""

import random
import string

from flask import jsonify, request

from db import fmt_dt, now
from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(now()),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created_response(data):
    return object_response(data, 201)


def empty_response(status=200):
    return object_response({}, status)


def list_response(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def pagination_params():
    """Read and validate the limit/offset query parameters."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET

    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "limit must be between %d and %d." % (MIN_LIMIT, MAX_LIMIT),
            )
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit, offset


def paginate_and_serialize(records, serializer):
    """Sort by created_at ascending, apply pagination, serialize."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return list_response([serializer(r) for r in page], total, limit, offset)
