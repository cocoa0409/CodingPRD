"""Pagination helpers (PRD §2.3).

limit default 10, min 1, max 100. offset default 0. List results ordered by
created_at ascending (we use the internal monotonic _seq for a stable tie-free
ordering that is consistent with created_at).
"""

from flask import request

import errors

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _parse_int(name, raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise errors.invalid_request(f"Query parameter '{name}' must be an integer.")


def get_pagination():
    """Return (limit, offset), validating bounds. Raises ERR_INVALID_REQUEST."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = LIMIT_DEFAULT
    else:
        limit = _parse_int("limit", limit_raw)
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise errors.invalid_request(
                f"limit must be between {LIMIT_MIN} and {LIMIT_MAX}."
            )

    if offset_raw is None:
        offset = OFFSET_DEFAULT
    else:
        offset = _parse_int("offset", offset_raw)
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0.")

    return limit, offset


def order_and_page(records, limit, offset):
    """Order by created_at ascending (stable via _seq) and slice the page.

    Returns (page_items, total_count).
    """
    ordered = sorted(records, key=lambda r: r.get("_seq", 0))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
