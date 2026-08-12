"""Standard response envelope helpers per PRD section 2.2 / 2.3."""

from flask import jsonify, request

import db
from errors import err_validation
from util import fmt_ts, new_req_id


def _meta_base():
    return {
        "api_request_id": new_req_id(),
        "api_request_timestamp": fmt_ts(db.now()),
    }


def ok(data, code=200, pagination=None):
    body = {
        "meta": _meta_base(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), code


def error_response(error_id, status, message):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(items):
    """Apply limit/offset per PRD 2.3 (default 10, min 1, max 100; offset default 0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_validation("limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_validation("offset must be an integer")
        if offset < 0:
            raise err_validation("offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
