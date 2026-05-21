"""Pagination parsing helpers — matches `response_envelope.pagination_defaults`."""
from __future__ import annotations

from typing import Tuple

from flask import request

from .errors import err_invalid_input


DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination() -> Tuple[int, int]:
    """Extract `limit` and `offset` query params, applying defaults and bounds.

    Raises ERR_INVALID_INPUT on out-of-range or malformed values.
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None or raw_limit == "":
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_input("limit must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err_invalid_input(f"limit must be in [{MIN_LIMIT}, {MAX_LIMIT}].")

    if raw_offset is None or raw_offset == "":
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_input("offset must be an integer.")
        if offset < 0:
            raise err_invalid_input("offset must be >= 0.")

    return limit, offset


def paginate(items, limit: int, offset: int):
    return items[offset:offset + limit]
