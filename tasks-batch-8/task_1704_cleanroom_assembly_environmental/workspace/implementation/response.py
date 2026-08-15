"""Standard response envelope helpers (PRD section 2.2 / 2.3)."""

import secrets
import string

from flask import jsonify

from db import now_iso
from errors import ApiError, ERR_INVALID_REQUEST


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": m, "response_type": "array", "data": items}), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def parse_pagination(args):
    """Parse and validate limit/offset query parameters (PRD section 2.3)."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit, 10)
        except (ValueError, TypeError):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "limit must be an integer between 1 and 100")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset, 10)
        except (ValueError, TypeError):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "offset must be a non-negative integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "offset must be a non-negative integer")
    return limit, offset


def paginate(records, args):
    """Apply default sort (created_at ASC) + pagination; return response."""
    from db import created_sort_key, pub  # local import to avoid cycle

    limit, offset = parse_pagination(args)
    ordered = sorted(records, key=created_sort_key)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([pub(r) for r in page], total, limit, offset)
