"""Response envelope of PRD 2.2 and the pagination contract of PRD 2.3."""

import random
import string

from flask import jsonify

from clock import clock
from constants import (
    PAGINATION_LIMIT_DEFAULT,
    PAGINATION_LIMIT_MAX,
    PAGINATION_LIMIT_MIN,
    PAGINATION_OFFSET_DEFAULT,
    PAGINATION_OFFSET_MIN,
)

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        # Server-generated ISO 8601 UTC timestamp with three fractional digits,
        # taken from the logical clock like every other server instant.
        "api_request_timestamp": clock.now_server_string(),
    }


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def array_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def read_pagination(args):
    """PRD 2.3: limit defaults to 10 (min 1, max 100); offset defaults to 0.
    Out-of-range or unparsable values are clamped to the documented bounds."""
    limit = PAGINATION_LIMIT_DEFAULT
    offset = PAGINATION_OFFSET_DEFAULT
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = PAGINATION_LIMIT_DEFAULT
        if limit < PAGINATION_LIMIT_MIN:
            limit = PAGINATION_LIMIT_MIN
        if limit > PAGINATION_LIMIT_MAX:
            limit = PAGINATION_LIMIT_MAX
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = PAGINATION_OFFSET_DEFAULT
        if offset < PAGINATION_OFFSET_MIN:
            offset = PAGINATION_OFFSET_MIN
    return limit, offset


def paginate(rows, args):
    limit, offset = read_pagination(args)
    total = len(rows)
    window = rows[offset : offset + limit]
    return window, limit, offset, total
