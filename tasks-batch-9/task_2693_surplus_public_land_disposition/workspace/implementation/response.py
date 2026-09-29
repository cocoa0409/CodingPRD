"""Response envelope helpers (PRD 2.2, 2.3)."""

import random
import string

from flask import jsonify, request

import clockmod
from errors import fail

_ALNUM = string.ascii_uppercase + string.ascii_lowercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clockmod.stamp(),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def empty_response(status=200):
    return object_response({}, status)


def list_response(rows, limit, offset, total_count):
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


def pagination():
    """Return the effective (limit, offset) pair, rejecting out-of-bounds values."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        if not _is_int(raw_limit):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        limit = int(raw_limit)
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if raw_offset is not None:
        if not _is_int(raw_offset):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        offset = int(raw_offset)
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def _is_int(text):
    try:
        int(text)
        return True
    except (TypeError, ValueError):
        return False


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
