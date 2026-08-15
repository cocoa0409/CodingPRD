"""Shared helpers for route modules: list plumbing and 404 lookups."""
from flask import request

from db import store
from errors import raise_error
from middleware import ALL_ROLES, get_caller, require_roles
from response import success_list
from validate import get_pagination


def require_record(collection, rid, error_id):
    rec = getattr(store, collection).get(rid)
    if rec is None:
        raise_error(error_id, f"{collection[:-1]} not found: {rid}")
    return rec


def list_endpoint(collection, serializer, filter_fields, sort_key=None):
    """All-role GET list: exact-match query filters, sort, paginate.

    A filter value of the literal string 'null' matches records whose field
    is None (used by salvage-items batch_id). Unknown values match nothing.
    """
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    limit, offset = get_pagination()
    items = list(getattr(store, collection).values())
    for field in filter_fields:
        value = request.args.get(field)
        if value is None:
            continue
        if value == "null":
            items = [r for r in items if r.get(field) is None]
        else:
            items = [r for r in items if r.get(field) == value]
    if sort_key is None:
        items.sort(key=lambda r: r["_seq"])
    else:
        items.sort(key=sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)
