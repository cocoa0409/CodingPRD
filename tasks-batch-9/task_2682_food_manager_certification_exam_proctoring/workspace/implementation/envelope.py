"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""
from flask import jsonify, request

from errors import ApiError
from store import iso3, jsonable, now_wall, request_id

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso3(now_wall()),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": jsonable(data if data is not None else {}),
    }
    return jsonify(body), status


def ok_list(rows, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [jsonable(r) for r in rows],
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def pagination():
    """Read and validate limit/offset. Raises ERR_INVALID_PAGINATION."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError("ERR_INVALID_PAGINATION",
                           "limit must be between 1 and 100")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be >= 0")
    return limit, offset


def window(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
