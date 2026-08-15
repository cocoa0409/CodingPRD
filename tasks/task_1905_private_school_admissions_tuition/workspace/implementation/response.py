"""Response envelope helpers — structure fixed by scaffold §1.0 / PRD §2.2."""

import random
import string

from flask import jsonify

import db
from errors import ApiError


def _request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def _meta() -> dict:
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.fmt_ts(db.wall_now()),
    }


def success(data, status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def _parse_pagination():
    from flask import request

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = 0
        if offset < 0:
            offset = 0
    return limit, offset


def success_list(items, status: int = 200):
    limit, offset = _parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + limit) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": page,
    }
    return jsonify(body), status


def error_response(e: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status
