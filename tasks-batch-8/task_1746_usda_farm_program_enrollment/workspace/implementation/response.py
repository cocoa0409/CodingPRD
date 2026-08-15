"""Standard response envelope helpers (PRD §2.2 / SCAFFOLD §1.0)."""

import random
import string

from flask import jsonify

from clock import iso_z
from datetime import datetime, timezone


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def _meta():
    now = datetime.now(timezone.utc)
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_z(now),
    }


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


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
    """Parse limit/offset query params per PRD §2.3.

    default limit 10, min 1, max 100, default offset 0.
    Out-of-range or malformed values are rejected by the caller as
    ERR_INVALID_REQUEST; this helper returns (limit, offset, error).
    """
    from errors import invalid_request

    raw_limit = args.get("limit")
    raw_offset = args.get("offset")

    limit = 10
    offset = 0

    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            return None, None, invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            return None, None, invalid_request("limit must be between 1 and 100")

    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            return None, None, invalid_request("offset must be an integer")
        if offset < 0:
            return None, None, invalid_request("offset must be >= 0")

    return limit, offset, None


def paginate(items, args):
    """Apply pagination to a full sorted list; returns a Flask response."""
    limit, offset, err = parse_pagination(args)
    if err is not None:
        raise err
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(page, limit, offset, total)
