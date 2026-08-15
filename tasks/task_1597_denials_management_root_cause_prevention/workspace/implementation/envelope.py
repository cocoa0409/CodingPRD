"""Response envelope helpers (PRD section 2.2 / 2.3)."""

import uuid

from flask import jsonify, request

from errors import ApiError, ERR_VALIDATION
from util import now_iso


def _meta(pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok(data, response_type="object", status=200, pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def pagination_params():
    """Parse limit/offset query parameters with defaults 10/0, bounds 1..100/0+."""
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    limit, offset = 10, 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_VALIDATION, 400, "limit must be between 1 and 100")
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_VALIDATION, 400, "offset must be >= 0")
    return limit, offset


def list_response(items):
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return ok(page, "array", 200, pagination)
