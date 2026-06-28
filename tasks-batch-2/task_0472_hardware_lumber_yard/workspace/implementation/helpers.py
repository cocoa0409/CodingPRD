"""Shared route helpers: lookups (with ERR_NOT_FOUND), list ordering."""
import errors


def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise errors.not_found()
    return rec


def sorted_by_creation(records):
    """PRD 2.3: lists sorted by created_at ascending (oldest first).

    We sort by the monotonic creation sequence to break created_at ties
    deterministically while preserving created_at-ascending order.
    """
    return sorted(records, key=lambda r: r["_seq"])


def paginate(records, limit, offset):
    """Apply pagination to an already-ordered list.

    Returns (page_items, total_count).
    """
    total = len(records)
    page = records[offset:offset + limit]
    return page, total
