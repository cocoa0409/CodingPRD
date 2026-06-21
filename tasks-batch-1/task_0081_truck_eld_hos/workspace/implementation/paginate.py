"""Shared list pagination: sort by created_at ASC (PRD §2.3), then slice."""


def paginate(items, limit, offset):
    items = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
