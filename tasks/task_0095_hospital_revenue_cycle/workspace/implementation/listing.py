"""List/pagination helpers (PRD 2.3). limit default 10, min 1, max 100;
offset default 0. Results ordered by created_at ascending (oldest first),
with insertion sequence as the tie-breaker."""
from flask import request

import errors


def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = 10
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer.")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100

    offset = 0
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer.")
        if offset < 0:
            offset = 0

    return limit, offset


def ordered(records):
    """Sort a collection by created_at ascending, with insertion seq tie-break."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(records):
    """Apply default ordering + pagination, returning (page, limit, offset, total)."""
    limit, offset = parse_pagination()
    ordered_records = ordered(records)
    total = len(ordered_records)
    page = ordered_records[offset:offset + limit]
    return page, limit, offset, total
