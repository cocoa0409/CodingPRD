"""Response envelope helpers (PRD §2.2) and pagination (PRD §2.3)."""

import random
import string

from flask import jsonify, request

from errors import fail
from store import now_iso, sort_rows, serialize_all

_ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
PAGE_OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def page_params():
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "limit must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            fail("ERR_VALIDATION", "limit must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "offset must be an integer.")
        if offset < PAGE_OFFSET_MIN:
            fail("ERR_VALIDATION", "offset must be at least 0.")
    return limit, offset


def ok_list(rows):
    """Sort, paginate and wrap a collection read."""
    limit, offset = page_params()
    ordered = sort_rows(rows)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    })
    body = {"meta": meta, "response_type": "array", "data": serialize_all(window)}
    return jsonify(body), 200
