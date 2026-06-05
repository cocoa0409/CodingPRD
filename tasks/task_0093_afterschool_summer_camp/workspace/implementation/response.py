"""Response envelope helpers (PRD §2.2, scaffold §1.0).

Envelope (verbatim from scaffold):
  success: { "meta": { "api_request_id", "api_request_timestamp" },
             "response_type": "object" | "array", "data": {} }
  error:   { "meta": {...}, "response_type": "error",
             "data": { "error_id", "message" } }
List responses add limit/offset/total_count/has_more inside meta.
"""
from __future__ import annotations

from typing import Any, Optional

from flask import jsonify

from db import new_request_id, now_iso
from errors import APIError, ERR_INVALID_REQUEST

# pagination defaults (scaffold §1.0 pagination_defaults)
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


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
        "data": data,
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
    """Read limit/offset from query args; defaults 10/0, limit in [1,100], offset >= 0."""
    limit_raw = args.get("limit", str(PAGE_DEFAULT_LIMIT))
    offset_raw = args.get("offset", str(PAGE_DEFAULT_OFFSET))
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise APIError(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
        raise APIError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if offset < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def slice_page(items: list, limit: int, offset: int) -> tuple:
    """Apply offset/limit slicing; returns (page_items, total_count)."""
    total = len(items)
    return items[offset : offset + limit], total
