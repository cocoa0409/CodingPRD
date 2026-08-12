"""Shared record plumbing: creation, mutation counter, pagination."""

import uuid

from flask import request

import db
from errors import fail


def new_record(record_id=None):
    """Common system fields for a freshly created resource."""
    ts = db.now()
    return {
        "id": record_id if record_id else str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(record):
    """§2.4: every mutation increments version by exactly 1 and refreshes updated_at."""
    record["version"] += 1
    record["updated_at"] = db.now()


def paginate(items):
    """limit/offset query params per §2.3: default 10, min 1, max 100, offset 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            fail("ERR_VALIDATION", "limit out of range [1, 100]")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            fail("ERR_VALIDATION", "offset must be >= 0")
    total = len(items)
    page = items[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta
