"""Response envelope helpers (PRD §2.2 / SCAFFOLD response_envelope).

Success: {"meta": {...}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {api_request_id, api_request_timestamp},
          "response_type": "error", "data": {"error_id", "message"}}
List responses add limit/offset/total_count/has_more to meta.
"""
import secrets

from flask import jsonify, request

from logical_clock import CLOCK
from util import isoformat


def _request_id():
    return "req_" + secrets.token_hex(12)


def _meta_base():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": isoformat(CLOCK.now()),
    }


def ok_object(data, status=200):
    body = {"meta": _meta_base(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset, status=200):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def parse_pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0 (PRD §2.3)."""
    from errors import ApiError, ERR_INVALID_REQUEST

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(rows):
    """rows: full filtered+sorted list of serialized dicts."""
    limit, offset = parse_pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list(page, total, limit, offset)
