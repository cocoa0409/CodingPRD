"""Shared route helpers: list serialization with filters and pagination."""
from db import db
from response import success_list
from services.core import public
from validate import get_pagination


def list_response(collection, filters=None):
    """List with created_at-ascending sort (PRD 2.3), exact-match filters, and
    limit/offset pagination. Ties on created_at break by insertion order."""
    items = list(getattr(db, collection).values())
    if filters:
        for field, value in filters.items():
            if value is None:
                continue
            items = [r for r in items if r.get(field) == value]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)
