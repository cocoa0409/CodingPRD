"""List sorting + windowing helper (PRD §2.3)."""


def sort_and_window(records, limit, offset):
    """Sort by created_at asc (id as a stable secondary), then apply offset/limit.

    Returns (page_items, total_count).
    """
    ordered = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
