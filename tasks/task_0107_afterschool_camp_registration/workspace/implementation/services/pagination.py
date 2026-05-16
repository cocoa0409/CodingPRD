"""Pagination helpers."""

from flask import request

from config import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)
from errors import APIError


def parse_pagination():
    """Read ?limit and ?offset, with default/min/max from config. Raise ERR_VALIDATION on bad input."""

    def _parse(name, default, minimum=None, maximum=None):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            v = int(raw)
        except (TypeError, ValueError):
            raise APIError("ERR_VALIDATION", f"{name} must be an integer.")
        if minimum is not None and v < minimum:
            raise APIError("ERR_VALIDATION", f"{name} below minimum {minimum}.")
        if maximum is not None and v > maximum:
            raise APIError("ERR_VALIDATION", f"{name} above maximum {maximum}.")
        return v

    limit = _parse(
        "limit",
        PAGINATION_DEFAULT_LIMIT,
        minimum=PAGINATION_MIN_LIMIT,
        maximum=PAGINATION_MAX_LIMIT,
    )
    offset = _parse("offset", PAGINATION_DEFAULT_OFFSET, minimum=0)
    return limit, offset


def paginate(rows, limit, offset, sort_key="created_at"):
    """Sort by sort_key ascending, then window."""
    sorted_rows = sorted(rows, key=lambda r: (r.get(sort_key) or "", r.get("id") or ""))
    total = len(sorted_rows)
    window = sorted_rows[offset : offset + limit]
    return window, total
