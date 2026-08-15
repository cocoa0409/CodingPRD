"""Shared route helpers: single-resource GET, filtered+paginated list GET."""
from flask import request

from db import db
from middleware import ALL_ROLES, authorized
from response import success_list, success_object
from services.core import serialize
from validate import get_pagination, require_path_resource


def get_one(collection: str, rid: str, what: str = "resource"):
    authorized(ALL_ROLES)
    rec = require_path_resource(collection, rid, what)
    return success_object(serialize(rec))


def list_response(collection: str, filters: dict):
    """filters: {field_name: raw_query_value_or_None}; exact string match."""
    authorized(ALL_ROLES)
    limit, offset = get_pagination()
    active = {k: v for k, v in filters.items() if v is not None}
    items = []
    for rec in db[collection].values():
        if all(_matches(rec.get(k), v) for k, v in active.items()):
            items.append(rec)
    # Every list response sorts by created_at ascending (PRD 2.3).
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(r) for r in page], total, limit, offset)


def _matches(value, raw):
    if value is None:
        return raw in ("", "null", "None")
    return str(value) == raw


def arg(name):
    return request.args.get(name)
