"""Standard response envelope helpers, matching the scaffold
`response_envelope` section exactly:

success: { "meta": {api_request_id, api_request_timestamp}, "response_type":
           "object" | "array", "data": {...} }
error:   { "meta": {...}, "response_type": "error",
           "data": {"error_id": ..., "message": ...} }
pagination fields live in `meta` on list responses: limit, offset,
total_count, has_more. Defaults: limit=10, min=1, max=100, offset=0.
"""

import random
import string

from flask import jsonify

import db
import errors as err


def _request_id() -> str:
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.wall_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def list_response(items, total_count, limit, offset):
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": api_error.error_id,
            "message": api_error.message,
        },
    }
    return jsonify(body), api_error.http_status


def parse_pagination(args):
    """Parse limit/offset query params per scaffold defaults (10 / 0, limit in
    [1,100], offset >= 0). Invalid values -> ERR_VALIDATION."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err.validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err.validation("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err.validation("offset must be an integer")
        if offset < 0:
            raise err.validation("offset must be >= 0")
    return limit, offset


def paginate(items, args):
    """Sort by created_at ascending (then id for stability) and paginate."""
    limit, offset = parse_pagination(args)
    ordered = sorted(items, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return list_response(page, total, limit, offset)
