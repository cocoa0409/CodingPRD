"""Shared lookup, listing, sorting, and pagination helpers."""
from db import db
from errors import err


def get_or_404(store, resource_id):
    entity = store.get(resource_id)
    if entity is None:
        raise err("ERR_NOT_FOUND", "Referenced resource does not exist.")
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
