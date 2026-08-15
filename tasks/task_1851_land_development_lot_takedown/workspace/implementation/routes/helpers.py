"""Shared route helpers: serialization and list pagination (PRD 2.3)."""
from db import db
from middleware import ALL_ROLES, authorized
from response import success_list, success_object
from validate import get_pagination, require_path


def public(rec):
    return dict(rec) if rec is not None else None


def list_response(collection, filters=None):
    """List with created_at-ascending sort, exact-match query filters, pagination."""
    authorized(ALL_ROLES)
    items = list(db[collection].values())
    for field, value in (filters or {}).items():
        if value is None:
            continue
        items = [r for r in items if r.get(field) == value]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


def get_one(collection, rid):
    authorized(ALL_ROLES)
    rec = require_path(collection, rid)
    return success_object(public(rec))
