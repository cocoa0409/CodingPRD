"""Shared route helpers: hierarchical existence checks (pipeline step 3) and
paginated listing."""

from db import db
from errors import err
from response import success_list
from services.validate import parse_pagination


def get_property_or_404(property_id):
    p = db["properties"].get(property_id)
    if p is None:
        err("ERR_NOT_FOUND", f"Property {property_id} not found")
    return p


def get_lease_or_404(lease_id):
    l = db["leases"].get(lease_id)
    if l is None:
        err("ERR_NOT_FOUND", f"Lease {lease_id} not found")
    return l


def get_child_or_404(collection, child_id, label):
    c = db[collection].get(child_id)
    if c is None:
        err("ERR_NOT_FOUND", f"{label} {child_id} not found")
    return c


def list_response(rows, filters=None):
    """Filters is a list of (query_value, predicate) pairs; a query value of
    None disables that predicate."""
    rows = list(rows)
    for qv, pred in filters or []:
        if qv is not None:
            rows = [r for r in rows if pred(r, qv)]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(rows)
    limit, offset = parse_pagination()
    page = rows[offset:offset + limit]
    return success_list(page, limit, offset, total)
