"""Response envelope helpers (PRD SS2.2) and pagination (PRD SS2.3)."""
import secrets
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits (wall clock)."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def _meta(extra=None):
    meta = {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def success_list(page_items, page_meta, code=200):
    body = {
        "meta": _meta(page_meta),
        "response_type": "array",
        "data": page_items,
    }
    return jsonify(body), code


def error_body(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def paginate(records, serializer):
    """Sort by created_at ASC (creation-sequence tie-break) and slice by
    limit/offset query params. Returns (list_payload, page_meta)."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return [serializer(r) for r in page], meta
