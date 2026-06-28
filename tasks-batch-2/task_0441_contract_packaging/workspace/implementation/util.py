"""Shared helpers: decimal rounding, pagination, body parsing (PRD §2.3, §2.8)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors

# Pagination defaults (SCAFFOLD §1.0 / PRD §2.3)
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def round_half_up(value, places):
    """Round a numeric value to `places` decimals using round-half-up.

    Uses Decimal to avoid IEEE-754 surprises. Returns a float for JSON.
    """
    if value is None:
        return None
    d = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)  # 10^-places
    rounded = d.quantize(quant, rounding=ROUND_HALF_UP)
    return float(rounded)


def to_decimal(value):
    return Decimal(str(value))


def get_json_body():
    """Return the parsed JSON body as a dict, or raise ERR_INVALID_REQUEST.

    A missing or non-object body for a write endpoint is malformed. An empty
    body (no content) is treated as an empty object for endpoints that take no
    fields, but POST actions that need fields will catch missing fields later.
    """
    if request.content_length in (None, 0) and not (request.data or b"").strip():
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


def parse_pagination():
    """Parse limit/offset query params with defaults and clamping (PRD §2.3).

    limit default 10, min 1, max 100. offset default 0.
    """
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET

    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise errors.invalid_request("limit must be an integer")
        if limit < PAGE_MIN_LIMIT:
            limit = PAGE_MIN_LIMIT
        elif limit > PAGE_MAX_LIMIT:
            limit = PAGE_MAX_LIMIT

    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            offset = 0

    return limit, offset


def paginate(items, limit, offset):
    """Slice a list and produce the pagination meta block.

    items must already be sorted (typically by created_at ASC -> _seq ASC).
    """
    total = len(items)
    window = items[offset:offset + limit]
    has_more = (offset + limit) < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return window, meta


def sort_by_creation(records):
    """Sort records by creation order ascending (PRD §2.3 created_at ASC).

    Uses the monotonic _seq counter as the stable creation order so identical
    logical-clock timestamps don't scramble ordering.
    """
    return sorted(records, key=lambda r: r.get("_seq", 0))


def require_fields(body, *names):
    """Ensure each named field is present (not None). -> ERR_INVALID_REQUEST."""
    for n in names:
        if n not in body or body[n] is None:
            raise errors.invalid_request("Missing required field: %s" % n)


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)
