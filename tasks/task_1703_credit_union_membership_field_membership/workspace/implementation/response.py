"""Standard response envelope helpers and pagination parsing."""
import secrets
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError


def _request_id():
    return "req_" + secrets.token_hex(12)


def now_iso():
    """Wall-clock ISO 8601 UTC timestamp with three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def ok_object(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def ok_list(items, total_count, limit, offset, status=200):
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": m, "response_type": "array", "data": items}), status


def error_body(err):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }), err.http_status


def parse_pagination():
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    if limit_s is None:
        limit = 10
    else:
        try:
            limit = int(limit_s)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION_FAILED", "limit must be an integer")
    if offset_s is None:
        offset = 0
    else:
        try:
            offset = int(offset_s)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION_FAILED", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION_FAILED", "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_VALIDATION_FAILED", "offset must be >= 0")
    return limit, offset


def paginate(items):
    """items: full sorted, filtered list. Returns a paginated array response."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list(page, total, limit, offset)
