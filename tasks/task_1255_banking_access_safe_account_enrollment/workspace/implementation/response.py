"""Standard response envelope helpers per SCAFFOLD §1.0 / PRD §2.2."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def _wall_timestamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _meta(include_pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _wall_timestamp(),
    }
    if include_pagination is not None:
        meta["limit"] = include_pagination["limit"]
        meta["offset"] = include_pagination["offset"]
        meta["total_count"] = include_pagination["total_count"]
        meta["has_more"] = include_pagination["has_more"]
    return meta


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """Parse limit/offset query params per SCAFFOLD pagination defaults."""
    from errors import err_validation

    raw_limit = args.get("limit", None)
    raw_offset = args.get("offset", None)

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            err_validation("limit must be an integer")
        if limit < 1 or limit > 100:
            err_validation("limit must be between 1 and 100")

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            err_validation("offset must be an integer")
        if offset < 0:
            err_validation("offset must be >= 0")

    return limit, offset
