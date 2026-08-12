"""Standard response envelope (PRD §2.2) and pagination helpers (PRD §2.3)."""
import secrets

from flask import jsonify, request

from errors import ERR_INVALID_REQUEST, raise_err
from util import wall_now_iso


def _request_meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": wall_now_iso(),
    }


def success_object(data, status=200):
    body = {"meta": _request_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _request_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(api_error):
    body = {
        "meta": _request_meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.http_status


def pagination_params():
    """limit defaults to 10, min 1, capped at 100; offset defaults to 0."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1:
            raise_err(ERR_INVALID_REQUEST, "limit must be at least 1")
        if limit > 100:
            limit = 100
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be at least 0")
    return limit, offset


def paginate(items):
    """items: full filtered list, already sorted by created_at ASC."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset : offset + limit]
    return success_list(page, limit, offset, total)
