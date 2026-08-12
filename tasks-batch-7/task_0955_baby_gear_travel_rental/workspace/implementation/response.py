"""Response envelope helpers — exact structure from PRD section 2.2:
success: { meta: {api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]},
           response_type: "object"|"array", data: ... }
error:   { meta: {api_request_id, api_request_timestamp}, response_type: "error",
           data: { error_id, message } }"""
import uuid

from flask import jsonify, request

from clock import now_dt
from errors import ApiError
from util import fmt_dt


def _request_id():
    return "req_" + uuid.uuid4().hex[:20]


def ok_obj(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": fmt_dt(now_dt()),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": fmt_dt(now_dt()),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(items) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def err_resp(error_id, message, status):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": fmt_dt(now_dt()),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def pagination_args():
    """limit defaults to 10, must be >= 1 and <= 100; offset defaults to 0."""
    limit, offset = 10, 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def paginate(records, serializer):
    """records pre-sorted; returns an envelope list response."""
    limit, offset = pagination_args()
    total = len(records)
    page = records[offset:offset + limit]
    return ok_list([serializer(r) for r in page], total, limit, offset)
