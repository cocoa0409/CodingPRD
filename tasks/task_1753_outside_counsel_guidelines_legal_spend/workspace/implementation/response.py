"""Standard response envelope helpers (PRD §2.2 / SCAFFOLD §1.0)."""

from flask import jsonify

import db
from errors import ApiError

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _meta(include_pagination=False, limit=None, offset=None, total_count=None):
    meta = {
        "api_request_id": db.new_request_id(),
        "api_request_timestamp": db.now_iso(),
    }
    if include_pagination:
        meta["limit"] = limit
        meta["offset"] = offset
        meta["total_count"] = total_count
        meta["has_more"] = (offset + limit) < total_count
    return meta


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    body = {
        "meta": _meta(True, limit, offset, total_count),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(err: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    """Parse limit/offset query params with scaffold defaults.

    limit: default 10, min 1, max 100. offset: default 0, min 0.
    Out-of-range values are clamped; non-numeric values fall back to defaults.
    """
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else PAGINATION_DEFAULT_LIMIT
    except (TypeError, ValueError):
        limit = PAGINATION_DEFAULT_LIMIT
    if limit < PAGINATION_MIN_LIMIT:
        limit = PAGINATION_MIN_LIMIT
    if limit > PAGINATION_MAX_LIMIT:
        limit = PAGINATION_MAX_LIMIT
    try:
        offset = int(raw_offset) if raw_offset is not None else PAGINATION_DEFAULT_OFFSET
    except (TypeError, ValueError):
        offset = PAGINATION_DEFAULT_OFFSET
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(records, limit, offset):
    """Sort by creation ascending (created_at, then insertion seq) and page."""
    ordered = sorted(records, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [public(r) for r in page], total


def public(rec: dict) -> dict:
    """Strip internal bookkeeping fields from a record."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
