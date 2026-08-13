"""Response envelope builders and pagination helpers.

Envelope (fixed by spec):
  success: {"meta": {...}, "response_type": "object"|"array", "data": ...}
  error:   {"meta": {...}, "response_type": "error",
            "data": {"error_id": ..., "message": ...}}
Pagination fields live inside meta: limit, offset, total_count, has_more.
"""
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError, raise_err

_ALNUM = string.ascii_letters + string.digits


def _meta():
    rid = "req_" + "".join(secrets.choice(_ALNUM) for _ in range(22))
    t = datetime.now(timezone.utc)
    ts = t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"
    return {"api_request_id": rid, "api_request_timestamp": ts}


def ok(data, status=200):
    payload = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(payload), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    payload = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(payload), 200


def err_response(error: ApiError):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error.error_id, "message": error.message},
    }
    return jsonify(payload), error.http_status


def parse_pagination():
    """Parse limit/offset query params.

    Defaults: limit=10 (min 1, max 100), offset=0 (min 0). Out-of-range
    values are clamped; non-integer values are a malformed request.
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err("ERR_INVALID_REQUEST", "limit must be an integer")
        if isinstance(limit, bool):
            raise_err("ERR_INVALID_REQUEST", "limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err("ERR_INVALID_REQUEST", "offset must be an integer")
        if isinstance(offset, bool):
            raise_err("ERR_INVALID_REQUEST", "offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def paginate(records, serializer):
    """Sort by created_at ASC (insertion order tie-break), paginate, serialize."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)
