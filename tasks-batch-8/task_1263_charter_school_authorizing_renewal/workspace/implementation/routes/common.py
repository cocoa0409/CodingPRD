"""Shared route helpers: existence, pagination, list filtering."""
from flask import request

import db
import errors
from errors import raise_error
from response import success_list


def get_or_404(collection: str, record_id: str):
    """Validation layer 3 — path existence, left-to-right."""
    record = db.get(collection, record_id)
    if record is None:
        raise_error(errors.ERR_NOT_FOUND, f"Resource not found: {record_id}")
    return record


def paginate(records):
    """PRD §2.3 — limit/offset with defaults; results sorted by created_at asc.

    Caller supplies records already filtered; this sorts + windows them.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(errors.ERR_INVALID_REQUEST, "limit out of range (1..100)")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(errors.ERR_INVALID_REQUEST, "offset must be >= 0")

    ordered = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return success_list(window, limit=limit, offset=offset, total_count=total)


def filter_eq(records, field: str, value):
    if value is None:
        return records
    # Numeric filter params (cycle_year, fiscal_year...) arrive as strings
    return [r for r in records if str(r.get(field)) == str(value)]
