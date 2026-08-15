"""Shared route helpers: serialization, pagination, list responses."""
from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND
from middleware import get_caller, require_roles
from response import success_list, success_object

ALL_READ_ROLES = ["BranchManager", "CounterRep", "RouteDispatcher", "WarehouseLead", "Account"]
STAFF_ROLES = ["BranchManager", "CounterRep", "RouteDispatcher", "WarehouseLead"]


def public(rec):
    """Strip internal bookkeeping fields (leading underscore)."""
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def get_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None or raw_limit == "":
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1:
            raise_error(ERR_INVALID_REQUEST, "limit must be >= 1")
        if limit > 100:
            limit = 100  # clamped at the maximum (PRD 2.3)
    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def _apply_filters(items, filters):
    for field, val in (filters or {}).items():
        if val is not None and val != "":
            items = [r for r in items if r.get(field) == val]
    return items


def list_response(collection, allowed_roles, filters=None, serializer=None):
    """List with auth, exact-match filters, created_at-ascending (_seq) sort, pagination."""
    caller = get_caller()
    require_roles(caller, allowed_roles)
    items = sorted(db[collection].values(), key=lambda r: r["_seq"])
    items = _apply_filters(items, filters)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    ser = serializer or public
    return success_list([ser(r) for r in page], total, limit, offset)


def get_one(collection, rid, allowed_roles, serializer=None):
    caller = get_caller()
    require_roles(caller, allowed_roles)
    rec = db[collection].get(rid)
    if rec is None:
        raise_error(ERR_RESOURCE_NOT_FOUND, f"{collection} id not found: {rid}")
    ser = serializer or public
    return success_object(ser(rec))
