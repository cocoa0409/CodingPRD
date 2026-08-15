"""Shared route helpers: serialization and list responses (PRD 2.3/2.4)."""
from db import db
from response import success_list
from validate import get_pagination


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sort_records(items):
    """created_at ascending (oldest first); insertion sequence breaks ties."""
    return sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


def list_response(collection, filters=None):
    items = list(db[collection].values())
    if filters:
        for field, value in filters.items():
            if value is None:
                continue
            items = [r for r in items if r.get(field) == value]
    items = sort_records(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


def list_from(items, filters=None):
    items = list(items)
    if filters:
        for field, value in filters.items():
            if value is None:
                continue
            items = [r for r in items if r.get(field) == value]
    items = sort_records(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)
