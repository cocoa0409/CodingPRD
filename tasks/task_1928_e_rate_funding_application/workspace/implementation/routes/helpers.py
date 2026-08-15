"""Shared route helpers: serialization, list pagination, read access (Any role)."""
from db import db
from middleware import get_caller
from response import success_list, success_object
from validate import get_pagination, require_path_resource


def public(rec):
    """Serialize a record, hiding internal bookkeeping keys (e.g. _seq)."""
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def list_collection(collection, filters=None):
    """GET list endpoints: open to every authenticated role (Any). Sorted by
    created_at ascending; exact-match query filters; limit/offset pagination."""
    get_caller()
    items = list(db[collection].values())
    if filters:
        for field, value in filters.items():
            if value is None:
                continue
            items = [r for r in items if r.get(field) == value]
    items.sort(key=lambda r: r["_seq"])
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


def get_one(collection, rid):
    """GET one resource: any authenticated role; 404 when the id is unknown."""
    get_caller()
    rec = require_path_resource(collection, rid)
    return success_object(public(rec))
