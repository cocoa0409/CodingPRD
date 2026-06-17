"""Existence resolution (priority 3, ERR_NOT_FOUND / 404) and pagination.

Path/body FK references are resolved left-to-right; the first missing one
yields ERR_NOT_FOUND (PRD §2.10).
"""
from flask import request

from db import db
from errors import err, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from domain import public

_STORES = {
    "container_model": "container_models",
    "protection_plan": "protection_plans",
    "depot": "depots",
    "depot_inventory": "depot_inventory",
    "customer": "customers",
    "rental_agreement": "rental_agreements",
    "container_unit": "container_units",
    "crew": "crews",
    "truck": "trucks",
    "delivery_job": "delivery_jobs",
    "move_order": "move_orders",
    "access_visit": "access_visits",
    "packing_supply_order": "packing_supply_orders",
    "charge": "charges",
}


def find(kind, entity_id):
    """Return the entity or raise ERR_NOT_FOUND."""
    store = getattr(db, _STORES[kind])
    ent = store.get(entity_id)
    if ent is None:
        raise err(ERR_NOT_FOUND, "%s %s not found." % (kind, entity_id))
    return ent


def maybe(kind, entity_id):
    """Return the entity or None (no raise)."""
    store = getattr(db, _STORES[kind])
    return store.get(entity_id)


# --------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# --------------------------------------------------------------------------
def paginate(rows):
    """rows: a list of public dicts already sorted. Returns (page, meta)."""
    limit = _int_param("limit", default=10, minimum=1, maximum=100)
    offset = _int_param("offset", default=0, minimum=0, maximum=None)
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        v = int(raw)
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "Query param %s must be an integer." % name)
    if minimum is not None and v < minimum:
        raise err(ERR_INVALID_REQUEST, "Query param %s must be >= %d." % (name, minimum))
    if maximum is not None and v > maximum:
        raise err(ERR_INVALID_REQUEST, "Query param %s must be <= %d." % (name, maximum))
    return v


def sorted_by_created(rows):
    """Default list ordering: created_at ASC (insertion seq breaks ties)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
