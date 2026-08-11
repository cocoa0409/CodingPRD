"""Standard response envelope per scaffold §1.0 / PRD §2.2.

Success: {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
          "response_type": "object"|"array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}
Pagination fields in meta: limit, offset, total_count, has_more.
"""

import secrets

from flask import jsonify, request

from errors import err
from store import now_iso, pub


def _meta(pag=None):
    m = {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": now_iso(),
    }
    if pag:
        m.update(pag)
    return m


def success(data, code=200, pag=None):
    body = {
        "meta": _meta(pag),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), code


def created(data):
    return success(data, 201)


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def paginate_args():
    """limit: default 10, min 1, max 100. offset: default 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Invalid pagination parameters")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def list_response(items):
    """Sort by created_at ascending, paginate, wrap in the envelope."""
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = paginate_args()
    total = len(items)
    page = items[offset:offset + limit]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return success([pub(e) for e in page], 200, pag)
