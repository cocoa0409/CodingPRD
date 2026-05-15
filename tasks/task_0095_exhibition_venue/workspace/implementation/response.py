"""Response envelope builders per PRD §2.2 and SCAFFOLD.response_envelope."""

import secrets
import string
from datetime import datetime, timezone
from flask import jsonify

from config import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MIN_LIMIT,
    PAGINATION_MAX_LIMIT,
)


def _now_iso():
    """ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _request_id():
    """Server-generated unique request id starting with req_."""
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }


def success(data, status_code=200):
    """Single-object success envelope."""
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status_code


def created(data):
    return success(data, status_code=201)


def success_list(items, total_count, limit, offset):
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


def error(error_id, message, status_code):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status_code


def parse_pagination(args):
    """Parse limit/offset from query args, applying defaults / clamp."""
    try:
        limit = int(args.get("limit", PAGINATION_DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = PAGINATION_DEFAULT_LIMIT
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(PAGINATION_MIN_LIMIT, min(limit, PAGINATION_MAX_LIMIT))
    offset = max(0, offset)
    return limit, offset
