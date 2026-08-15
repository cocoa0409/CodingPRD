"""Standard response envelope helpers (SCAFFOLD §1.0 / PRD §2.2).

Success:
  { "meta": {"api_request_id": "req_...", "api_request_timestamp": "ISO8601",
             ...pagination for lists...},
    "response_type": "object" | "array",
    "data": ... }
Error:
  { "meta": {"api_request_id": ..., "api_request_timestamp": ...},
    "response_type": "error",
    "data": {"error_id": "...", "message": "..."} }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return f"req_{suffix}"


def _request_timestamp() -> str:
    dt = datetime.now(timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S.")
    s += f"{dt.microsecond // 1000:03d}Z"
    return s


def success(data, status: int = 200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, limit: int, offset: int, total_count: int):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + limit) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error(error_id: str, message: str, http_status: int):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def parse_pagination(args) -> tuple[int, int]:
    """Parse limit/offset query params per SCAFFOLD pagination_defaults.

    limit default 10, min 1, max 100; offset default 0. Malformed or
    out-of-range values are clamped/failed per ERR_INVALID_REQUEST.
    """
    from errors import bad_request

    raw_limit = args.get("limit", None)
    raw_offset = args.get("offset", None)

    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise bad_request("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad_request("offset must be an integer")
        if offset < 0:
            raise bad_request("offset must be >= 0")
    return limit, offset
