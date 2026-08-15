"""Response envelope helpers (PRD §2.2, §2.3)."""

import uuid
from flask import jsonify, request

from db import fmt_ts, now
from errors import ApiError, ERR_VALIDATION, raise_err


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_ts(now()),
    }


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def get_body():
    """Parse the JSON request body. Missing body -> {}; malformed -> ERR_VALIDATION."""
    data = request.get_data(cache=True)
    if data is None or len(data.strip()) == 0:
        return {}
    import json
    try:
        parsed = json.loads(data)
    except Exception:
        raise_err(ERR_VALIDATION, "Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        raise_err(ERR_VALIDATION, "Request body must be a JSON object.")
    return parsed


def pagination_params():
    """limit/offset per PRD §2.3: default 10, min 1, max 100, offset default 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "limit must be an integer.")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "offset must be an integer.")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items):
    """Apply pagination to an already-filtered, already-sorted list."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(page, limit, offset, total)
