"""Standard response envelope helpers per PRD §2.2 / §2.3."""

import random
import string
from flask import jsonify

from db import store
from errors import ApiError


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return f"req_{suffix}"


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.now_iso(),
    }


def success_object(data, status_code=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status_code


def success_list(items, limit, offset, total_count):
    meta = _meta()
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
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    """Parse limit/offset query params per §2.3: default 10, min 1, max 100, offset default 0."""
    from errors import raise_error, ERR_INVALID_REQUEST

    raw_limit = args.get("limit")
    raw_offset = args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")

    return limit, offset
