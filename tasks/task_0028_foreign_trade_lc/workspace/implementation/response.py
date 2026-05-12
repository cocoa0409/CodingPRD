"""Response envelope builders per PRD §2.2."""

import secrets
import string
from datetime import datetime, timezone
from flask import jsonify

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100


def _now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }


def success(data, status_code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status_code


def success_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error(error_id, message, status_code):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status_code


def parse_pagination(args):
    """Extract limit/offset; raise ERR_INVALID_REQUEST if outside bounds."""
    from errors import raise_error, ERR_INVALID_REQUEST
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise_error(ERR_INVALID_REQUEST, "limit must be integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise_error(ERR_INVALID_REQUEST, f"limit must be between {PAGINATION_MIN_LIMIT} and {PAGINATION_MAX_LIMIT}")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise_error(ERR_INVALID_REQUEST, "offset must be integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be non-negative")
    return limit, offset
