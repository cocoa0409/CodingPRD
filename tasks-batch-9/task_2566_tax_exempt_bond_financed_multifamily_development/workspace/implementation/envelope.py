"""Standard success / error response envelopes (PRD section 2.2) and pagination."""

from flask import jsonify, request

from errors import ApiError, fail
from store import new_request_id, wall_now_iso


PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _base_meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": wall_now_iso(),
    }


def object_response(data, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def empty_response(status=200):
    return object_response({}, status)


def list_response(rows, limit, offset, total_count):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def read_pagination():
    """Parse and validate `limit` / `offset` query parameters."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET

    if raw_limit is not None:
        limit = _as_int(raw_limit, "limit")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            fail("ERR_INVALID_REQUEST",
                 "limit must be between %d and %d." % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT))
    if raw_offset is not None:
        offset = _as_int(raw_offset, "offset")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be greater than or equal to 0.")
    return limit, offset


def _as_int(raw, name):
    text = raw.strip()
    if text == "":
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    try:
        return int(text, 10)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)


def paginate(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, total


def apply_list(serialized_rows):
    limit, offset = read_pagination()
    window, total = paginate(serialized_rows, limit, offset)
    return list_response(window, limit, offset, total)
