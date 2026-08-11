"""Standard response envelope helpers (PRD §2.2 / §2.3)."""
import secrets
from datetime import datetime, timezone

from flask import jsonify, request

from db import iso
from errors import ApiError, ERR_INVALID_REQUEST


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(11),
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }


def ok_obj(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(api_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    return jsonify(body), api_err.http_status


def parse_pagination():
    """limit: default 10, min 1, max 100; offset: default 0, min 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(400, ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(400, ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(400, ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise ApiError(400, ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items):
    """Apply pagination to a pre-sorted list; returns (response, )."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list(page, total, limit, offset)


def bool_param(name):
    """Optional boolean query flag; None when absent."""
    raw = request.args.get(name)
    if raw is None:
        return None
    v = raw.strip().lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no"):
        return False
    raise ApiError(400, ERR_INVALID_REQUEST, f"{name} must be a boolean")
