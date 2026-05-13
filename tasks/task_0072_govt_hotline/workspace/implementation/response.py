"""Standard response envelope per PRD §2.2."""

from flask import jsonify, request

import clock
import db

PAGINATION_DEFAULT = 10
PAGINATION_MIN = 1
PAGINATION_MAX = 100


def _meta():
    return {
        "api_request_id": db.request_id(),
        "api_request_timestamp": clock.now_iso(),
    }


def success(data, status_code: int = 200):
    """Single-object success."""
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }), status_code


def success_list(items, total_count: int, limit: int, offset: int):
    """List/array success with pagination meta fields."""
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = int(total_count)
    meta["has_more"] = (offset + limit) < int(total_count)
    return jsonify({
        "meta": meta,
        "response_type": "array",
        "data": items,
    }), 200


def error(error_id: str, message: str, status_code: int):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status_code


def parse_pagination():
    """Read limit/offset query params. Raises ERR_VALIDATION on out-of-range values."""
    from errors import AppError, ERR_VALIDATION, ERROR_STATUS

    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    try:
        limit = int(raw_limit) if raw_limit is not None else PAGINATION_DEFAULT
    except (ValueError, TypeError):
        raise AppError(ERR_VALIDATION, "limit must be an integer", ERROR_STATUS[ERR_VALIDATION])
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (ValueError, TypeError):
        raise AppError(ERR_VALIDATION, "offset must be an integer", ERROR_STATUS[ERR_VALIDATION])

    if limit < PAGINATION_MIN or limit > PAGINATION_MAX:
        raise AppError(
            ERR_VALIDATION,
            f"limit must be between {PAGINATION_MIN} and {PAGINATION_MAX}",
            ERROR_STATUS[ERR_VALIDATION],
        )
    if offset < 0:
        raise AppError(ERR_VALIDATION, "offset must be >= 0", ERROR_STATUS[ERR_VALIDATION])
    return limit, offset


def paginate(items: list, limit: int, offset: int) -> list:
    return items[offset: offset + limit]
