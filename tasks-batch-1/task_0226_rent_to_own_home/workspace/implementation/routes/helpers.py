"""Shared route helpers: lookups, pagination, ownership."""

from flask import request

import db
from errors import err

PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def lookup(store, rid):
    """Existence check (priority 3). Returns record or raises ERR_NOT_FOUND."""
    rec = store.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Referenced resource does not exist")
    return rec


def parse_pagination():
    """Read limit/offset query params with defaults/min/max from PRD §2.3.

    Out-of-range / malformed pagination params are well-formedness violations
    (ERR_INVALID_REQUEST, 422)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = PAGE_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            raise err("ERR_INVALID_REQUEST",
                      f"limit must be between {PAGE_MIN_LIMIT} and {PAGE_MAX_LIMIT}")

    if raw_offset is None:
        offset = PAGE_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")

    return limit, offset


def paginate(items):
    """Sort by created_at asc, then apply limit/offset. Returns (page, limit,
    offset, total_count)."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


def agreement_tenant_id(agreement):
    return agreement.get("tenant_id")


def agreement_landlord_id(agreement):
    return agreement.get("landlord_id")
