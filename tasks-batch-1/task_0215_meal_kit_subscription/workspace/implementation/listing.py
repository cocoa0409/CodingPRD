"""List helpers: filtering, default created_at-asc sort, pagination (PRD §2.3)."""


def sort_key(e):
    # Primary: created_at asc; secondary: insertion sequence for ties.
    return (e["created_at"], e["_seq"])


def paginate(items, limit, offset):
    """Return (page, total_count). items already filtered + sorted."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
