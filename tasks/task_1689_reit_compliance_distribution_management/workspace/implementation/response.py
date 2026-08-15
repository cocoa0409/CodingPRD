"""Response envelope helpers per SCAFFOLD §1.0 and PRD §2.2/§2.3.

Success envelope:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601 3-frac-digits" },
    "response_type": "object" | "array", "data": ... }
  List responses add limit/offset/total_count/has_more into meta.

Error envelope:
  { "meta": { api_request_id, api_request_timestamp }, "response_type": "error",
    "data": { "error_id": ..., "message": ... } }
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

from db import db


def _request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return f"req_{suffix}"


def _request_timestamp():
    """ISO 8601 UTC with three fractional digits (milliseconds)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """Parse limit/offset query params per §2.3: limit default 10 (min 1, max 100),
    offset default 0. Out-of-range values are clamped per the declared envelope."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(rows, limit, offset):
    """Sort by created_at ascending, then slice. Rows are dicts with created_at."""
    ordered = sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
