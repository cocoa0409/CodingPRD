"""Standard response envelope (PRD section 2.2) and pagination (PRD 2.3)."""

import random
import string

from flask import jsonify

from errors import fail
from store import fmt_dt, store

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

_ALPHABET = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(store.now),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
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


def read_pagination(args):
    """Parse and validate limit/offset query parameters."""
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is not None and raw_limit != "":
        limit = _as_int(raw_limit)
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        offset = _as_int(raw_offset)
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be greater than or equal to 0.")
    return limit, offset


def _as_int(raw):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Pagination parameters must be integers.")


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]
