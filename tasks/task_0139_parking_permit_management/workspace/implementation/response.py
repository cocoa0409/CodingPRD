"""Response envelope helpers (PRD §2.2 / §2.3 / scaffold response_envelope)."""
from __future__ import annotations

from typing import Any, Optional

from flask import jsonify

from db import new_request_id, now_iso
from errors import APIError, ERR_PAGINATION_INVALID


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
    """Read limit/offset query params (PRD §2.3).

    Defaults: limit=10 (min 1, max 100), offset=0 (min 0). Out-of-bounds or
    non-integer values are rejected with ERR_PAGINATION_INVALID (HTTP 400).
    """
    limit_raw = args.get("limit", None)
    offset_raw = args.get("offset", None)

    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise APIError(ERR_PAGINATION_INVALID, 400, "limit must be an integer")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise APIError(ERR_PAGINATION_INVALID, 400, "offset must be an integer")

    if limit < 1 or limit > 100:
        raise APIError(ERR_PAGINATION_INVALID, 400, "limit must be between 1 and 100")
    if offset < 0:
        raise APIError(ERR_PAGINATION_INVALID, 400, "offset must be >= 0")
    return limit, offset


def slice_page(items: list, limit: int, offset: int) -> tuple:
    """Apply offset/limit slicing; returns (page_items, total_count)."""
    total = len(items)
    return items[offset : offset + limit], total
