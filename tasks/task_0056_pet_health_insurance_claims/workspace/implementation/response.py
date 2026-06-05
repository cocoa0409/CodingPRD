"""Response envelope helpers (PRD §2.2 / §2.3)."""
from __future__ import annotations

from typing import Any, Optional
from flask import jsonify

from db import new_request_id, now_iso

# Internal bookkeeping fields that must never appear in responses.
_HIDDEN = ("_seq",)


def _public(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: v for k, v in obj.items() if k not in _HIDDEN}
    if isinstance(obj, list):
        return [_public(x) for x in obj]
    return obj


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
        "data": _public(data),
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
        "data": _public(items),
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
    """Read limit/offset from request.args (default 10/0, min 1, max 100)."""
    from errors import APIError, ERR_INVALID_REQUEST

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


def slice_page(items: list, limit: int, offset: int) -> tuple:
    total = len(items)
    return items[offset : offset + limit], total
