"""Response envelope (PRD 2.2) and pagination contract (PRD 2.3)."""

import random
import string

from flask import jsonify

from timeutil import clock

_ALPHANUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
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
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def read_pagination(args):
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = LIMIT_DEFAULT
        limit = max(LIMIT_MIN, min(LIMIT_MAX, limit))
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = OFFSET_DEFAULT
        offset = max(OFFSET_DEFAULT, offset)
    return limit, offset


def list_response(rows, args):
    limit, offset = read_pagination(args)
    total = len(rows)
    window = rows[offset:offset + limit]
    return array_response(window, limit, offset, total)
