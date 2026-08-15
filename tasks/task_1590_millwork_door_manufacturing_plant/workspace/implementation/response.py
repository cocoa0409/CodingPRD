"""Standard response envelope helpers (PRD §2.2 / §2.3)."""

import random
import string

from flask import jsonify

import db


def _request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_iso(),
    }
    if pagination:
        meta.update(pagination)
    return meta


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def parse_pagination(args):
    """Parse limit/offset per PRD §2.3: limit default 10, min 1, max 100 (clamped); offset default 0."""
    raw_limit = args.get("limit")
    if raw_limit is None or raw_limit == "":
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    raw_offset = args.get("offset")
    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = 0
        if offset < 0:
            offset = 0
    return limit, offset


def list_response(items, limit, offset, serializer):
    """Serialize, sort (created_at asc, insertion order stable), paginate, and wrap a list."""
    ordered = sorted(items, key=lambda r: r["created_at"])
    total = len(ordered)
    window = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return success([serializer(r) for r in window], status=200, response_type="array", pagination=pagination)
