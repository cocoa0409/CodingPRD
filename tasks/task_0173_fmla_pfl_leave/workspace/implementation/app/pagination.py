"""Pagination param helpers (limit/offset)."""
from __future__ import annotations

from typing import Tuple

from flask import request

from .errors import err_validation


DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination() -> Tuple[int, int]:
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None or raw_limit == "":
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_validation("limit must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err_validation(f"limit must be in [{MIN_LIMIT}, {MAX_LIMIT}].")

    if raw_offset is None or raw_offset == "":
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_validation("offset must be an integer.")
        if offset < 0:
            raise err_validation("offset must be >= 0.")

    return limit, offset


def slice_page(items, limit: int, offset: int):
    return items[offset:offset + limit]
