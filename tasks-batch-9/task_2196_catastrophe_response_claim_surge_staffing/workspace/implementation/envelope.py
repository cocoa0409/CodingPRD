"""Response envelope helpers (PRD section 2.2) and pagination (PRD section 2.3)."""
import datetime as _dt

from flask import jsonify, request

import store
from errors import fail


def _meta():
    now = _dt.datetime.now(_dt.timezone.utc)
    return {
        "api_request_id": store.request_id(),
        "api_request_timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.")
        + "%03dZ" % (now.microsecond // 1000),
    }


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object",
            "data": data if data is not None else {}}
    return jsonify(body), code


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def error_body(error_id, message):
    return {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}


def pagination():
    """Read and validate limit/offset.  Violations are ERR_VALIDATION (422)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        if raw_limit.strip() == "":
            fail("ERR_VALIDATION", "limit must be an integer between 1 and 100.")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "limit must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            fail("ERR_VALIDATION", "limit must be between 1 and 100.")
    if raw_offset is not None:
        if raw_offset.strip() == "":
            fail("ERR_VALIDATION", "offset must be a non-negative integer.")
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "offset must be a non-negative integer.")
        if offset < 0:
            fail("ERR_VALIDATION", "offset must be at least 0.")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]
