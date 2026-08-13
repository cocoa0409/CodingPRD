"""Response envelope (SCAFFOLD §1.0 / PRD §2.2-2.3) and pagination."""

import secrets

from flask import jsonify, request

from errors import ApiError, err
from helpers import render_dt, now


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": render_dt(now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(e: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


def parse_pagination():
    """limit (default 10, 1..100), offset (default 0, >=0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(records, sort_key=None):
    """Sort by created_at ASC (insertion seq tie-break), then paginate."""
    limit, offset = parse_pagination()
    key = sort_key or (lambda r: (r["created_at"], r["_seq"]))
    ordered = sorted(records, key=key)
    page = ordered[offset:offset + limit]
    return page, limit, offset, len(ordered)
