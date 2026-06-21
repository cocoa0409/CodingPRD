"""Pagination parameter parsing (PRD §2.3)."""
from __future__ import annotations

from typing import Tuple
from flask import request

from errors import APIError, ERR_INVALID_REQUEST


def parse_pagination() -> Tuple[int, int]:
    """Return (limit, offset). Defaults: limit=10, offset=0. limit in [1, 100]."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise APIError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise APIError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise APIError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise APIError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")

    return limit, offset


def sort_by_created(rows: list) -> list:
    return sorted(rows, key=lambda r: r.get("created_at", ""))
