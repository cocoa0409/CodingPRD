"""Standard response envelope (PRD §2.2) and pagination (PRD §2.3)."""

import random
import string

from flask import jsonify

from errors import ApiError
from store import now_iso3

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso3(),
    }


def ok(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(err):
    return jsonify(error_body(err.error_id, err.message)), err.http_status


# --------------------------------------------------------------- pagination --

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100


def parse_pagination(args):
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0).

    Out-of-range values are ERR_INVALID_REQUEST, never silently clamped.
    """
    limit = DEFAULT_LIMIT
    offset = 0
    raw_limit = args.get("limit", None)
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(str(raw_limit))
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    raw_offset = args.get("offset", None)
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(str(raw_offset))
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
