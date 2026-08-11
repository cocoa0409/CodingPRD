"""The response envelope exactly as SCAFFOLD.response_envelope / PRD 2.2 fix it.

  success: { "meta": { "api_request_id", "api_request_timestamp"
                       [, "limit", "offset", "total_count", "has_more"] },
             "response_type": "object" | "array", "data": ... }
  error:   { "meta": { "api_request_id", "api_request_timestamp" },
             "response_type": "error",
             "data": { "error_id", "message" } }
"""

from flask import jsonify

import config
from db import DB, IDS
from errors import ApiError
from tsutil import ts_canonical


def _meta():
    return {
        "api_request_id": IDS.request_id(),
        # case A: canonical three-fractional-digit rendering of the logical clock
        "api_request_timestamp": ts_canonical(DB.now_dt()).s,
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(exc):
    assert isinstance(exc, ApiError)
    return jsonify(error_body(exc.error_id, exc.message)), exc.http_status


def paginate(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total


def page_args(args):
    """Rung 4: limit in 1..100, offset >= 0; anything else is ERR_VALIDATION."""
    limit = config.PAGE_LIMIT_DEFAULT
    offset = config.PAGE_OFFSET_DEFAULT
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(str(raw_limit))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer.")
        if limit < config.PAGE_LIMIT_MIN or limit > config.PAGE_LIMIT_MAX:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(str(raw_offset))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be zero or greater.")
    return limit, offset
