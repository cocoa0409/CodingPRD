"""Response envelope builders per PRD §2."""

import uuid
from datetime import datetime, timezone
from flask import jsonify

from config import PAGINATION_DEFAULT_LIMIT, PAGINATION_MAX_LIMIT, PAGINATION_MIN_LIMIT


def _meta():
    """Base meta object: request ID + timestamp."""
    return {
        "api_request_id": f"mkt_{uuid.uuid4().hex[:20]}",
        "api_request_timestamp": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S."
        ) + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z",
    }


def success(data, status_code=200):
    """Single-object success response."""
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status_code


def success_list(items, total_count, limit=None, offset=None):
    """Paginated list success response."""
    limit = limit or PAGINATION_DEFAULT_LIMIT
    offset = offset or 0
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error(error_id, message, status_code):
    """Error response envelope."""
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status_code


def parse_pagination(args):
    """Extract and clamp limit/offset from request args."""
    try:
        limit = int(args.get("limit", PAGINATION_DEFAULT_LIMIT))
    except (ValueError, TypeError):
        limit = PAGINATION_DEFAULT_LIMIT
    try:
        offset = int(args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
    limit = max(PAGINATION_MIN_LIMIT, min(limit, PAGINATION_MAX_LIMIT))
    offset = max(0, offset)
    return limit, offset
