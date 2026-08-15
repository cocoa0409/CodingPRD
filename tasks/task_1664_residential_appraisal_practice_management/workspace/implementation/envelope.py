"""Response envelope of PRD 2.2 and the pagination contract of PRD 2.3."""

import random
import string

from flask import jsonify

from errors import ApiError
from timeutil import render_meta_timestamp

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": render_meta_timestamp(),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object",
            "data": data if data is not None else {}}
    return jsonify(body), status


def array_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def read_pagination(args):
    """PRD 2.3: limit default 10, min 1, max 100; offset default 0."""
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100.")
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be non-negative.")
    return limit, offset


def paginate(rows, args):
    limit, offset = read_pagination(args)
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, limit, offset, total
