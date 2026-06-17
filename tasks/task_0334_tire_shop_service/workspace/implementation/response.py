"""Response envelope helpers (PRD §2.2 / scaffold §1.0).

Success envelope:
  { "meta": {api_request_id, api_request_timestamp, [pagination...]},
    "response_type": "object" | "array", "data": {...} }
Error envelope:
  { "meta": {api_request_id, api_request_timestamp},
    "response_type": "error", "data": {error_id, message} }
"""
from __future__ import annotations

from typing import Any, Optional, Tuple

from flask import jsonify

from db import new_request_id, now_iso, public


def _meta(extra: Optional[dict] = None) -> dict:
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data: Any, http_status: int = 200):
    if isinstance(data, dict):
        data = public(data)
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), http_status


def ok_array(items: list, limit: int, offset: int, total_count: int,
             http_status: int = 200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": has_more,
            }
        ),
        "response_type": "array",
        "data": [public(i) if isinstance(i, dict) else i for i in items],
    }
    return jsonify(body), http_status


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status


def paginate_params(args) -> Tuple[int, int]:
    """Read pagination params (PRD §2.3).

    Defaults: limit=10, offset=0. Min limit=1, max limit=100, min offset=0.
    Out-of-range / malformed values surface ERR_INVALID_REQUEST (HTTP 422).
    """
    from errors import APIError, ERR_INVALID_REQUEST

    limit_raw = args.get("limit", "10")
    offset_raw = args.get("offset", "0")
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise APIError(ERR_INVALID_REQUEST, 422, "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise APIError(ERR_INVALID_REQUEST, 422, "limit must be between 1 and 100")
    if offset < 0:
        raise APIError(ERR_INVALID_REQUEST, 422, "offset must be >= 0")
    return limit, offset


def slice_page(items: list, limit: int, offset: int) -> Tuple[list, int]:
    total = len(items)
    return items[offset: offset + limit], total
