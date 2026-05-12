"""Response envelope helpers per PRD §2.2."""

from __future__ import annotations

from flask import jsonify

import db
from config import PAGINATION_DEFAULT_LIMIT, PAGINATION_MAX_LIMIT, PAGINATION_MIN_LIMIT
from errors import AppError, ERR_INVALID_REQUEST


def _meta() -> dict:
    return {
        "api_request_id": db.new_request_id(),
        "api_request_timestamp": db.now_iso(),
    }


def success(data, status_code: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status_code


def success_list(items, total_count: int, limit: int, offset: int):
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    })
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error(error_id: str, message: str, status_code: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status_code


def parse_pagination(args) -> tuple[int, int]:
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")

    if raw_limit is None or raw_limit == "":
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise AppError(ERR_INVALID_REQUEST, "limit must be integer", 400)
    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise AppError(ERR_INVALID_REQUEST, "offset must be integer", 400)

    if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        raise AppError(ERR_INVALID_REQUEST,
                       f"limit must be between {PAGINATION_MIN_LIMIT} and {PAGINATION_MAX_LIMIT}",
                       400)
    if offset < 0:
        raise AppError(ERR_INVALID_REQUEST, "offset must be >= 0", 400)
    return limit, offset
