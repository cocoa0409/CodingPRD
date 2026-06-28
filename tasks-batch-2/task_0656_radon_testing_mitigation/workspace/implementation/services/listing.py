"""Filtered-list + pagination helper. Sorts by created_at ascending (PRD §2.3)."""

from services.domain import public


def paginate(collection, filters, limit, offset):
    """Filter a dict-of-entities by exact-match `filters` (skipping None values),
    sort by created_at ascending (tie-break creation seq), apply offset/limit, and
    return (public_items, total_count)."""
    items = list(collection.values())
    for field, expected in filters.items():
        if expected is None:
            continue
        items = [e for e in items if e.get(field) == expected]
    items.sort(key=lambda e: (e["_created_dt"], e["_seq"]))
    total = len(items)
    window = items[offset:offset + limit]
    return [public(e) for e in window], total
