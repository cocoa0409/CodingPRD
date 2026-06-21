"""Response envelope helpers (PRD §2.2, scaffold §1.0).

Success object:
  { "meta": {api_request_id, api_request_timestamp},
    "response_type": "object", "data": {...} }
Success array adds pagination fields (limit, offset, total_count, has_more) to meta.
Error:
  { "meta": {...}, "response_type": "error",
    "data": {error_id, message} }
"""
from __future__ import annotations

from typing import Any, Optional
from flask import jsonify

from db import new_request_id, now_iso
from errors import APIError, ERR_INVALID_REQUEST


def _meta(extra: Optional[dict] = None) -> dict:
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data: Any, http_status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), http_status


def ok_array(items: list, limit: int, offset: int, total_count: int, http_status: int = 200):
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
        "data": items,
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


def paginate_params(args) -> tuple:
    """Read pagination params with defaults (limit 10/min 1/max 100, offset 0).

    Raises APIError(ERR_INVALID_REQUEST, 400) on bad types or out-of-range.
    """
    limit_raw = args.get("limit", "10")
    offset_raw = args.get("offset", "0")
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise APIError(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise APIError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if offset < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def sort_and_page(items: list, limit: int, offset: int) -> tuple:
    """Sort by created_at ASC (PRD §2.3), then slice. Returns (page, total)."""
    ordered = sorted(items, key=lambda o: (o.get("created_at", ""), o.get("id", "")))
    total = len(ordered)
    return ordered[offset : offset + limit], total
