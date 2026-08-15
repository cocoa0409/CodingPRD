"""Response envelope helpers, transcribed from PRD §2.2 / §2.3."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def _envelope_timestamp() -> str:
    """ISO 8601 UTC timestamp with three fractional digits (wall clock for
    the meta envelope only — entity timestamps use the logical clock)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def success_object(data, status: int = 200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _envelope_timestamp(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit: int, offset: int, total_count: int, status: int = 200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _envelope_timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id: str, message: str, status: int):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _envelope_timestamp(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status


def parse_pagination(args):
    """Parse limit/offset query params with defaults limit=10, offset=0,
    min 1, max 100. Invalid values fall back to defaults per scaffold."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0
    return limit, offset
