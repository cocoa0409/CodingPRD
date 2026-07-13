"""Standard response envelope (PRD §2.2) and pagination (PRD §2.3)."""
import random
import string

from flask import jsonify, request

import db
from errors import ApiError

ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(ALNUM) for _ in range(20)),
        "api_request_timestamp": db.iso(db.now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, status=200, pagination=None):
    meta = _meta()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def read_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT

    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "limit must be between %d and %d." % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX),
            )

    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset may not be negative.")

    return limit, offset


def paginate(records, serializer):
    """Sort by created_at ASC, slice, and build the list envelope."""
    limit, offset = read_pagination()
    ordered = db.by_creation(records)
    total = len(ordered)
    page = ordered[offset: offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return ok_list([serializer(r) for r in page], 200, pagination)
