"""Response envelope helpers (PRD §2.2, §2.3) and pagination parsing."""
import random
import string

from flask import jsonify, request

import db
from errors import ApiError, ERR_INVALID_REQUEST

PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_ts(),
    }


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, limit, offset, total_count):
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": m, "response_type": "array", "data": items}), 200


def err(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def parse_pagination():
    """Parse limit/offset query params with PRD §2.3 defaults and bounds."""
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            raise ApiError(
                ERR_INVALID_REQUEST, 400,
                "limit must be between %d and %d" % (PAGE_MIN_LIMIT, PAGE_MAX_LIMIT),
            )
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def paginate(items, serializer=None):
    """Sort by created_at ascending (stable for ties), window, and wrap."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    limit, offset = parse_pagination()
    total = len(ordered)
    page = ordered[offset:offset + limit]
    if serializer is not None:
        page = [serializer(r) for r in page]
    return ok_list(page, limit, offset, total)
