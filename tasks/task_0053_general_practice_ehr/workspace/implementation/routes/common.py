"""Shared route helpers: path lookups (404), pagination, list filtering."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from flask import request

import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def lookup_or_404(store: Dict[str, Dict[str, Any]], resource_id: str, what: str) -> Dict[str, Any]:
    """Priority 3: path-referenced resource exists, else ERR_NOT_FOUND (PRD §2.6)."""
    rec = store.get(resource_id)
    if rec is None:
        raise APIError(ERR_NOT_FOUND, 404, f"{what} not found")
    return rec


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3). Out-of-range -> ERR_INVALID_REQUEST."""
    limit = _parse_int_param("limit", PAGINATION_DEFAULT_LIMIT)
    offset = _parse_int_param("offset", PAGINATION_DEFAULT_OFFSET)
    if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        raise APIError(
            ERR_INVALID_REQUEST, 422,
            f"limit must be between {PAGINATION_MIN_LIMIT} and {PAGINATION_MAX_LIMIT}",
        )
    if offset < 0:
        raise APIError(ERR_INVALID_REQUEST, 422, "offset must be >= 0")
    return limit, offset


def _parse_int_param(name: str, default: int) -> int:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{name} must be an integer")


def sort_by_created(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Default sort: created_at ascending (oldest first) — PRD §2.3.

    created_at strings can collide at millisecond granularity; use insertion
    order (id minted sequentially via dict insertion) as a stable tiebreak by
    relying on Python's stable sort over a pre-ordered list.
    """
    return sorted(records, key=lambda r: r.get("created_at", ""))


def paginate(records: List[Dict[str, Any]], limit: int, offset: int):
    total = len(records)
    window = records[offset:offset + limit]
    return window, total
