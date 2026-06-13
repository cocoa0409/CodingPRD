"""Shared list sorting + pagination (PRD §2.3)."""
from middleware import serialize


def sort_key(rec):
    # Sort by created_at ascending; _seq breaks identical-timestamp ties
    # deterministically in creation order.
    return (rec.get("created_at", ""), rec.get("_seq", 0))


def paginate(records, limit, offset):
    """Sort by created_at asc, slice, return (serialized_page, total_count)."""
    ordered = sorted(records, key=sort_key)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serialize(r) for r in page], total
