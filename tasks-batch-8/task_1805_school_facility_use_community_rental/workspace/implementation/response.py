"""Standard response envelope per PRD §2.2 / SCAFFOLD §1.0.

Success: { meta: {api_request_id, api_request_timestamp[, limit, offset,
total_count, has_more]}, response_type: "object"|"array", data: ... }
Error:   { meta: {api_request_id, api_request_timestamp},
           response_type: "error", data: {error_id, message} }
"""
import random
import string

from flask import jsonify, request

import errors
import util


def _meta_base():
    return {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_uppercase + string.digits, k=20)
        ),
        "api_request_timestamp": util.clock_iso(),
    }


def success(payload, status=200):
    body = {"meta": _meta_base(), "response_type": "object", "data": payload}
    return jsonify(body), status


def success_list(items, total_count, limit, offset, status=200):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error(err):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def pagination_params():
    """limit: default 10, min 1, max 100; offset: default 0, min 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0")
    return limit, offset


def paginate(rows):
    """rows: full filtered list (already sorted). Applies limit/offset."""
    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list(page, total, limit, offset)
