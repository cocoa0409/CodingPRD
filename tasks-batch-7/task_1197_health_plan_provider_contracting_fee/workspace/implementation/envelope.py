"""Response envelope helpers (PRD section 2.2 / 2.3)."""

import random
import string

from flask import jsonify, request

from store import now_iso

# Pagination defaults from the scaffold response_envelope section.
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(pagination=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def ok(data, status=200):
    """Single-resource (or empty-object) success envelope."""
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def page_params():
    try:
        limit = int(request.args.get("limit", DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(MIN_LIMIT, min(MAX_LIMIT, limit))
    try:
        offset = int(request.args.get("offset", DEFAULT_OFFSET))
    except (TypeError, ValueError):
        offset = DEFAULT_OFFSET
    offset = max(0, offset)
    return limit, offset


def ok_list(items, status=200):
    """Paginated list envelope. Items must already be filtered and sorted."""
    limit, offset = page_params()
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": page,
    }
    return jsonify(body), status


def error_resp(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status
