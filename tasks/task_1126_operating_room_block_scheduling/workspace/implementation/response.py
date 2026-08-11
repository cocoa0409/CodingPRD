"""Standard response envelope helpers (SCAFFOLD §1.0 / PRD §2.2-2.3)."""

import random
import string

from flask import jsonify, request

from errors import ApiError, ERR_INVALID_REQUEST
from util import now_iso


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def success_object(payload, status=200):
    body = {"meta": meta(), "response_type": "object", "data": payload}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + limit) < total_count
    body = {"meta": m, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def get_pagination():
    """Parse and clamp limit/offset query parameters.

    limit: default 10, min 1, max 100. offset: default 0, min 0.
    Non-integer values are a request-shape failure.
    """
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(records):
    """records: full filtered list, already sorted by created_at ASC."""
    limit, offset = get_pagination()
    total = len(records)
    page = records[offset:offset + limit]
    return success_list(page, limit, offset, total)
