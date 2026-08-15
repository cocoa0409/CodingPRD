"""Response envelope helpers (scaffold section 1.0 / PRD section 2.2)."""
import uuid

from flask import jsonify, request

from db import fmt_wall, wall_now


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_wall(wall_now()),
    }


def ok(data, code=200, response_type="object", pagination=None):
    body = {"meta": _meta(), "response_type": response_type, "data": data}
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), code


def ok_obj(data, code=200):
    return ok(data, code=code, response_type="object")


def ok_list(items, total_count, limit, offset):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return ok(items, code=200, response_type="array", pagination=pagination)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def pagination_params():
    """limit: default 10, min 1, max 100 (capped). offset: default 0, min 0."""
    from errors import ApiError, ERR_VALIDATION

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError(ERR_VALIDATION, 400, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError(ERR_VALIDATION, 400, "offset must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(rows):
    """Rows arrive sorted by creation order (created_at ascending)."""
    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total, limit, offset
