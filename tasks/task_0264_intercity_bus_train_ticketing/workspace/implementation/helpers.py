"""Shared request helpers: pagination parsing and list packaging."""
from flask import request

from errors import err
from constants import (
    PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT,
    PAGINATION_DEFAULT_OFFSET, PAGINATION_MIN_OFFSET,
)


def parse_pagination():
    """Parse + validate limit/offset query params (PRD 2.3).

    Out-of-bounds -> ERR_VALIDATION_PAGINATION (422).
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION_PAGINATION", "limit is not an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise err("ERR_VALIDATION_PAGINATION", "limit out of bounds")

    if raw_offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION_PAGINATION", "offset is not an integer")
        if offset < PAGINATION_MIN_OFFSET:
            raise err("ERR_VALIDATION_PAGINATION", "offset out of bounds")

    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at asc (insertion seq as tiebreak), slice, build meta."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = offset + limit < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta


def get_json_body():
    """Return the request JSON body as a dict (empty dict if none/invalid)."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body
