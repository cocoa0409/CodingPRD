"""List endpoint helper (PRD 2.3)."""


def page(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total
