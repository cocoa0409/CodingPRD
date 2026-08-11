"""Response envelope (PRD §2.2, §2.3) — meta / response_type / data."""
import secrets

from flask import jsonify, request

import clock
from errors import ApiError, invalid_request
from util import iso_ms


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(8),
        "api_request_timestamp": iso_ms(clock.now()),
    }


def ok(data, response_type="object", status=200):
    body = {"meta": _meta(), "response_type": response_type, "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(exc):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    return jsonify(body), exc.http_status


def pagination_params():
    """limit / offset per §2.3: default 10 / 0, limit within 1..100."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid_request("limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid_request("offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items):
    """items: full filtered, created_at-ascending list of serialized dicts."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list(page, total, limit, offset)
