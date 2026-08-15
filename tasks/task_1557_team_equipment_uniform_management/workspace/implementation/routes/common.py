"""Shared route helpers: list rendering with filters and pagination."""
from db import sorted_all, serialize
from middleware import pagination_params
from response import success_list

ALL_ROLES = ("EquipmentManager", "TeamAdmin", "LaundryVendor")


def render_list(coll, filters=None, serializer=None):
    """Sorted by created_at ascending (insertion order breaks ties);
    limit/offset pagination fields in meta (PRD §2.3)."""
    items = sorted_all(coll)
    if filters:
        for key, value in filters.items():
            if value is not None:
                items = [e for e in items if e.get(key) == value]
    total = len(items)
    limit, offset = pagination_params()
    page = items[offset : offset + limit]
    ser = serializer or (lambda e: serialize(e))
    return success_list([ser(e) for e in page], total, limit, offset)
