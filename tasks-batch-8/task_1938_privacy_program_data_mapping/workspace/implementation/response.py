"""Response envelope helpers (PRD section 2.2 / 2.3)."""
import uuid

from flask import jsonify, request

import clock
from errors import ApiError
from utils import fmt_ts


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_ts(clock.now()),
    }


def success(data, status=200, response_type="object", pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination():
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def list_response(items, serializer):
    """items must already be sorted (created_at ASC)."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return success(
        [serializer(x) for x in page],
        200,
        response_type="array",
        pagination=pagination,
    )
