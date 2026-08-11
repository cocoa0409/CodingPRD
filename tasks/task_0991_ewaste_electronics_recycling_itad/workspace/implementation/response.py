"""Response envelope helpers (SCAFFOLD §1.0 / PRD §2.2-2.3).

Success: { "meta": {api_request_id, api_request_timestamp},
           "response_type": "object"|"array", "data": ... }
List responses add limit/offset/total_count/has_more into meta.
Error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error", "data": {error_id, message} }
"""

import uuid
from datetime import datetime, timezone

from flask import jsonify, request

import clocktime
from errors import ApiError, ERR_VALIDATION


def _request_id():
    return "req_" + uuid.uuid4().hex[:20]


def _request_ts():
    return clocktime.fmt_ts(datetime.now(timezone.utc))


def ok_object(data, code=200):
    payload = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_ts(),
        },
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(payload), code


def ok_list(items, total_count, limit, offset, code=200):
    payload = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_ts(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(payload), code


def error_response(error_id, status, message):
    payload = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_ts(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(payload), status


def parse_pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0 (PRD §2.3)."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(str(limit_raw).strip())
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_VALIDATION, 400, "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(str(offset_raw).strip())
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_VALIDATION, 400, "offset must be >= 0")
    return limit, offset


def paginate(records, code=200):
    """records: full filtered list, already sorted created_at ASC."""
    limit, offset = parse_pagination()
    total = len(records)
    page = records[offset:offset + limit]
    return ok_list(page, total, limit, offset, code=code)


def sort_created(records):
    return sorted(records, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
