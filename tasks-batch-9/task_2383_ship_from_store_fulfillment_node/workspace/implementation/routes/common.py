"""Shared route plumbing: existence lookups, node scope and the version glue."""
from flask import g

from constants import ROLE_ASSOCIATE
from db import get
from errors import ApiError
from response import array_response, object_response, paged_response, serialize
from services import derive

NOT_FOUND = {
    "stores": "ERR_STORE_NOT_FOUND",
    "skus": "ERR_SKU_NOT_FOUND",
    "inventories": "ERR_INVENTORY_NOT_FOUND",
    "packaging": "ERR_PACKAGING_NOT_FOUND",
    "pickups": "ERR_PICKUP_NOT_FOUND",
    "orders": "ERR_ORDER_NOT_FOUND",
    "order_lines": "ERR_ORDER_LINE_NOT_FOUND",
    "routing_runs": "ERR_ROUTING_RUN_NOT_FOUND",
    "candidates": "ERR_CANDIDATE_NOT_FOUND",
    "assignments": "ERR_ASSIGNMENT_NOT_FOUND",
    "assignment_lines": "ERR_ASSIGNMENT_LINE_NOT_FOUND",
    "windows": "ERR_WINDOW_NOT_FOUND",
    "notifications": "ERR_NOTIFICATION_NOT_FOUND",
}


def fetch(kind, row_id):
    """Priority 4 / 5: resolve an id or raise the collection's 404."""
    row = get(kind, row_id)
    if row is None:
        raise ApiError(NOT_FOUND[kind])
    return row


def require_scope(actor, role, store_id):
    """Priority 6: a StoreAssociate only acts inside its own node."""
    if role == ROLE_ASSOCIATE and actor != store_id:
        raise ApiError("ERR_STORE_SCOPE_VIOLATION")


def commit(explicit=()):
    derive.commit(g.pre, explicit=explicit)


def show(row):
    """Read-only projection: a GET never recomputes or bumps anything."""
    return object_response(serialize(row))


def finish(row, status=200, explicit=()):
    commit(explicit)
    return object_response(serialize(row), status)


def finish_array(rows, explicit=()):
    commit(explicit)
    return array_response([serialize(r) for r in rows])


def listing(rows, limit, offset):
    return paged_response(rows, limit, offset)


def apply_filter(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]
