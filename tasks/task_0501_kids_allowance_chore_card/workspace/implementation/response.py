"""Standard response envelope (PRD §2.2) and pagination (PRD §2.3)."""
import random
import string

from flask import jsonify

import db
from errors import ApiError, ERROR_STATUS


def _request_id():
    return "req_" + "".join(
        random.choices(string.ascii_letters + string.digits, k=20)
    )


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status=200, response_type="object", meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def object_response(data, status=200):
    return success(data, status=status, response_type="object")


def error_response(error_id, message):
    status = ERROR_STATUS[error_id]
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message or error_id},
    }
    return jsonify(body), status


def api_error_response(exc):
    return error_response(exc.error_id, exc.message)


PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def parse_pagination(args):
    """Read limit/offset query params with defaults/min/max from PRD §2.3.
    A malformed value falls back to its default rather than erroring."""
    def to_int(name, default):
        raw = args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    limit = to_int("limit", PAGE_DEFAULT_LIMIT)
    offset = to_int("offset", PAGE_DEFAULT_OFFSET)
    if limit < PAGE_MIN_LIMIT:
        limit = PAGE_MIN_LIMIT
    if limit > PAGE_MAX_LIMIT:
        limit = PAGE_MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(items, args):
    """Sort by created_at ascending (PRD §2.3), paginate, and wrap with the
    pagination meta fields limit/offset/total_count/has_more."""
    ordered = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(ordered)
    limit, offset = parse_pagination(args)
    page = ordered[offset:offset + limit]
    has_more = (offset + limit) < total
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return success(page, status=200, response_type="array", meta_extra=meta_extra)
