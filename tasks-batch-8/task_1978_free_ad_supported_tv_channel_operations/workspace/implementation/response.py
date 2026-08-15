"""Standard response envelope helpers, matching the scaffold's
response_envelope section exactly:

success: { "meta": {api_request_id, api_request_timestamp[, pagination]},
           "response_type": "object"|"array", "data": ... }
error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error", "data": {error_id, message} }
"""

import secrets
import string

from flask import jsonify, request

from db import now_str
from errors import raise_err, ERR_INVALID_REQUEST

ALPHANUM = string.ascii_letters + string.digits

PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(secrets.choice(ALPHANUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_str()}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def ok_array(items, status=200):
    body = {"meta": _meta(), "response_type": "array", "data": items}
    return jsonify(body), status


def no_content():
    return ("", 204)


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def parse_pagination():
    """limit: default 10, clamped into [1, 100]; offset: default 0, floored
    at 0. Non-integer values are rejected as a shape error."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = PAGE_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise_err(ERR_INVALID_REQUEST, "Query parameter 'limit' must be an integer")
        limit = max(PAGE_MIN_LIMIT, min(PAGE_MAX_LIMIT, limit))
    if raw_offset is None:
        offset = PAGE_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise_err(ERR_INVALID_REQUEST, "Query parameter 'offset' must be an integer")
        offset = max(PAGE_DEFAULT_OFFSET, offset)
    return limit, offset


def paginate(records, serialize):
    """Sort by created_at ascending (insertion order as tie-break), apply
    pagination, and build the list envelope."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return ok_list([serialize(r) for r in page], total, limit, offset)
