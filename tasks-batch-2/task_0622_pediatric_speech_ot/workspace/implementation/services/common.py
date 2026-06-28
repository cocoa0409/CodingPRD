"""Shared record helpers: creation, mutation bumping, lookup, pagination."""

import errors
from errors import ApiError
from db import db


def new_record(extra=None):
    """Create a record with common system fields (PRD §2.4).

    id, created_at, updated_at, version. Caller merges in entity fields.
    """
    now = db.now_iso()
    rec = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    if extra:
        rec.update(extra)
    return rec


def touch(rec):
    """Mark a resource mutated: refresh updated_at and increment version.

    PRD §2.4: updated_at refreshed on any change including computed fields;
    version increments by one on every mutation.
    """
    rec["updated_at"] = db.now_iso()
    rec["version"] = rec["version"] + 1


def lookup(store, rec_id):
    """Return the record or raise ERR_NOT_FOUND (PRD §2.5)."""
    if rec_id is None or rec_id not in store:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Resource not found.")
    return store[rec_id]


def paginate(items, args):
    """Apply limit/offset pagination (PRD §2.3). Returns (page, limit, offset, total)."""
    total = len(items)
    limit = _parse_pagination_int(args.get("limit"), default=10, minimum=1, maximum=100)
    offset = _parse_pagination_int(args.get("offset"), default=0, minimum=0, maximum=None)
    page = items[offset : offset + limit]
    return page, limit, offset, total


def _parse_pagination_int(raw, default, minimum, maximum):
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (ValueError, TypeError):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Invalid pagination parameter.")
    if minimum is not None and value < minimum:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Pagination parameter out of range.")
    if maximum is not None and value > maximum:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Pagination parameter out of range.")
    return value


def sorted_by_created(records):
    """PRD §2.3: list endpoints sort by created_at ascending."""
    return sorted(records, key=lambda r: (r["created_at"], r["id"]))
