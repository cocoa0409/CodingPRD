"""Shared lookup, listing, sorting, and pagination helpers."""
from errors import err


def get_or_404(store, resource_id):
    """Path-referenced resource lookup (priority 3 -> ERR_NOT_FOUND)."""
    entity = store.get(resource_id)
    if entity is None:
        raise err("ERR_NOT_FOUND", "Referenced resource does not exist.")
    return entity


def get_ref_or_404(store, resource_id):
    """Body foreign-key lookup (priority 4 -> ERR_REFERENCE_NOT_FOUND)."""
    entity = store.get(resource_id)
    if entity is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced foreign key does not exist.")
    return entity


def sort_by_created(items):
    """Default sort: creation timestamp ascending. The monotonic _seq breaks ties."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def paginate(items, limit, offset):
    """Returns (page_items, total_count) after sorting by creation order."""
    ordered = sort_by_created(items)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
