"""Standard response envelope helpers (PRD §2.2 / §2.3)."""

import secrets
import string
from flask import jsonify, request

from db import fmt_iso, clock_now
from errors import ApiError, err400, ERR_INVALID_REQUEST


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta_base():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_iso(clock_now()),
    }


def success_object(data, status=200):
    body = {
        "meta": _meta_base(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(err: ApiError):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination():
    """Read and validate limit/offset query params per PRD §2.3."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err400(ERR_INVALID_REQUEST, "limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise err400(ERR_INVALID_REQUEST, "limit must be in [1,100]")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err400(ERR_INVALID_REQUEST, "offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            raise err400(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset
