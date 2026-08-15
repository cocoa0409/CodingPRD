"""Shared request-shape helpers: body parsing, type guards, pagination."""

from flask import request

from errors import validation

TRADES = ("PLUMBING", "ELECTRICAL", "HVAC", "APPLIANCE", "GENERAL")
PRIORITIES = ("EMERGENCY", "URGENT", "ROUTINE")
ASSIGNMENT_TYPES = ("IN_HOUSE", "VENDOR")
ENTRY_AUTHS = ("EMERGENCY_ACCESS", "RESIDENT_CONSENT", "NOTICE_POSTED")

# Pagination defaults/bounds (PRD 2.3).
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def body():
    """JSON request body as a dict; anything else behaves as an empty object."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_str(v):
    return isinstance(v, str)


def pagination():
    """Parse limit/offset query params (PRD 2.3); out-of-range is malformed."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None or raw_limit == "":
        limit = PAGE_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit, 10)
        except (TypeError, ValueError):
            validation("limit must be an integer")
        if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            validation("limit out of range")
    if raw_offset is None or raw_offset == "":
        offset = PAGE_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset, 10)
        except (TypeError, ValueError):
            validation("offset must be an integer")
        if offset < 0:
            validation("offset must be >= 0")
    return limit, offset


def sorted_page(records, limit, offset):
    """Default list ordering: created_at ascending (PRD 2.3), insertion order
    breaks ties (stable sort over the insertion-ordered tables)."""
    ordered = sorted(records, key=lambda r: r["created_at"])
    total = len(ordered)
    return ordered[offset:offset + limit], total
