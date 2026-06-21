"""Shared helpers: timestamps, common fields, pagination, body parsing.

PRD §2.4: versioned mutable entities carry id, created_at, updated_at, version.
Immutable audit records (FxRate, SanctionsListEntry, SanctionsHit, LedgerEntry)
carry only id and created_at. Timestamps are ISO 8601 UTC with three fractional
digits, derived from the logical clock.
"""
from flask import request

import db
from errors import err


def now_iso():
    """Logical-clock instant as ISO 8601 UTC with three fractional digits."""
    dt = db.get_clock()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def stamp_create(record, versioned=True):
    """Populate id/created_at (+ updated_at/version for versioned entities)."""
    ts = now_iso()
    record["id"] = db.new_id()
    record["created_at"] = ts
    record["_seq"] = db.next_seq()
    if versioned:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def touch(record):
    """Bump version and refresh updated_at on a mutation (PRD §2.4)."""
    record["version"] += 1
    record["updated_at"] = now_iso()


def public(record):
    """Strip internal fields (those prefixed with _) for the response."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def get_json():
    """Parse the request JSON body, tolerating an empty/missing body as {}."""
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10 (min 1, max 100), offset default 0.
# ---------------------------------------------------------------------------
def paginate(items):
    """Sort by created_at asc (PRD §2.3, stable seq tiebreak), then page.

    Returns (page_items, pagination_meta).
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = 10
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100

    offset = 0
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            offset = 0
        if offset < 0:
            offset = 0

    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def require_fields(body, fields):
    """Ensure required fields are present and non-null (ERR_INVALID_REQUEST)."""
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def positive_int(body, field):
    """Require a strictly-positive integer amount (ERR_INVALID_REQUEST)."""
    val = body.get(field)
    if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a positive integer")
    return val
