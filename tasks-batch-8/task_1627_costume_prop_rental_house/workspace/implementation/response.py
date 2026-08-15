"""Standard response envelope helpers (PRD section 2.2 / 2.3)."""

import random
import string

from flask import jsonify, request

from db import now_iso, public
from errors import fail


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }


def respond_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def _pagination_params():
    """Parse limit/offset query params per PRD 2.3 (default 10 / 0, clamp 1..100)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            fail("ERR_VALIDATION", "limit must be an integer")
        if isinstance(limit, bool):
            fail("ERR_VALIDATION", "limit must be an integer")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            fail("ERR_VALIDATION", "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def respond_list(records, status=200, paginate=True):
    """records: list of public-serialized resources, already sorted."""
    if paginate:
        limit, offset = _pagination_params()
    else:
        limit, offset = 10, 0
    total = len(records)
    page = records[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": page,
    }
    return jsonify(body), status


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def serialize(rec):
    return public(rec)


def serialize_many(recs):
    return [public(r) for r in recs]
