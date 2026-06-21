"""Shared list-endpoint helper: sort by created_at ASC (PRD §2.3), then
paginate, then return the standard array envelope with pagination meta."""
from domain import serialize
from response import success
from validation import parse_pagination


def sort_created_at(rows):
    # created_at ascending; ties broken by the monotonic creation sequence so the
    # ordering is stable even within the same millisecond.
    return sorted(rows, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def list_response(rows):
    limit, offset = parse_pagination()
    ordered = sort_created_at(rows)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return success([serialize(r) for r in page], status=200, is_array=True, pagination=pagination)
