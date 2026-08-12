"""Response envelope helpers (SCAFFOLD §1.0 / PRD §2.2-2.3)."""
import uuid

from flask import jsonify, request

from errors import fail
from util import wall_now_iso


def _meta(pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": wall_now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok_object(data, status=200):
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }), status


def ok_list(items, total_count, limit, offset):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    }
    return jsonify({
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }), 200


def error_body(error_id, message, status):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status


def parse_pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    try:
        limit = 10 if raw_limit is None else int(raw_limit)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = 0 if raw_offset is None else int(raw_offset)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1 or limit > 100:
        fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        fail("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def list_response(records, view_fn):
    """Sort by created_at ASC (insertion order tiebreak), paginate, serialize."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([view_fn(r) for r in page], total, limit, offset)
