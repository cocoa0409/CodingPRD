"""Pagination, rounding, and request-parsing helpers."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0


def round_half_up(value, places=0):
    """Round a numeric value half-up to the given number of decimal places.

    Returns int when places==0, else a Decimal.
    """
    q = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    d = Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)
    if places == 0:
        return int(d)
    return d


def parse_pagination():
    """Read and validate limit/offset query params (PRD §2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = PAGINATION_LIMIT_DEFAULT
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_VALIDATION_OUT_OF_RANGE, "limit must be an integer")
        if limit < PAGINATION_LIMIT_MIN or limit > PAGINATION_LIMIT_MAX:
            raise errors.err(errors.ERR_VALIDATION_OUT_OF_RANGE, "limit out of range")

    if raw_offset is None:
        offset = PAGINATION_OFFSET_DEFAULT
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_VALIDATION_OUT_OF_RANGE, "offset must be an integer")
        if offset < 0:
            raise errors.err(errors.ERR_VALIDATION_OUT_OF_RANGE, "offset out of range")

    return limit, offset


def paginate(items, limit, offset):
    """Return the page slice; items must already be sorted."""
    total = len(items)
    window = items[offset:offset + limit]
    return window, total


def sort_by_created(items):
    """Sort resources by created_at ascending, tie-break by insertion seq."""
    return sorted(items, key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))


def get_json_body():
    """Return the JSON request body as a dict, or raise ERR_INVALID_REQUEST."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % f)
