"""Response envelope helpers (PRD 2.2 / 2.3)."""
import random
import string

from flask import jsonify, request

import timeutil
from errors import ApiError, fail

ALNUM = string.ascii_uppercase + string.digits
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": request_id(), "api_request_timestamp": timeutil.now_audit()}


def ok(data=None, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data=None):
    return ok(data, 201)


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def pagination():
    """Read limit/offset from the query string, validating shape and range."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_FIELD_VALUE", "limit must be an integer.")
        if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            fail("ERR_INVALID_FIELD_VALUE", "limit must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_FIELD_VALUE", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_FIELD_VALUE", "offset must be at least 0.")
    return limit, offset


def listing(rows, serializer=None):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    if serializer is not None:
        page = [serializer(r) for r in page]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(page) < total
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), 200


__all__ = ["ok", "created", "listing", "error_response", "ApiError", "pagination"]
