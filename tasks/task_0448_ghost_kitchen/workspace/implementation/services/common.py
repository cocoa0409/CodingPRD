"""Common entity-lifecycle helpers: id/timestamps/version management,
serialization, pagination, and FK existence resolution.

Common system fields (PRD §2.4): id, created_at, updated_at, version.
RecipeComponent is the lone exception — only id + created_at (no updated_at,
no version).
"""
from flask import request

import errors
from db import store


# Per-entity field whitelists used for serialization (exact output shapes).
ENTITY_FIELDS = {
    "Stall": ["name", "timezone", "open_minute_of_day", "close_minute_of_day",
              "status", "equipment_count"],
    "VirtualBrand": ["name", "owner_email", "commission_rate_bps",
                     "availability", "status", "ledger_balance_cents"],
    "KitchenLease": ["stall_id", "brand_id", "monthly_fee_cents",
                     "priority_rank", "status"],
    "Equipment": ["stall_id", "equipment_type", "turnaround_buffer_minutes",
                  "status"],
    "EquipmentBooking": ["equipment_id", "order_id", "start_minute",
                         "end_minute", "status"],
    "MenuItem": ["brand_id", "name", "price_cents", "prep_minutes",
                 "required_equipment_type", "availability"],
    "IngredientLot": ["stall_id", "ingredient_name", "received_at",
                      "unit_cost_cents_per_gram", "grams_received",
                      "grams_remaining"],
    "AggregatorOrder": ["brand_id", "aggregator", "external_ref", "line_items",
                        "routed_stall_id", "booking_id", "gross_revenue_cents",
                        "commission_cents", "food_cost_cents", "status"],
    "RecipeComponent": ["menu_item_id", "ingredient_name", "quantity_grams"],
}


def new_entity(entity_type, fields, with_version=True):
    """Build a fresh record with system-managed fields populated.

    with_version=False is used for RecipeComponent (id + created_at only)."""
    now = store.now_iso()
    rec = dict(fields)
    rec["id"] = store.new_id()
    rec["_type"] = entity_type
    rec["_seq"] = store.next_seq()
    rec["created_at"] = now
    if with_version:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Mutation: bump version by 1, refresh updated_at (PRD §2.4)."""
    rec["version"] += 1
    rec["updated_at"] = store.now_iso()


def serialize(rec):
    """Project a stored record to its public JSON shape."""
    etype = rec["_type"]
    out = {"id": rec["id"], "created_at": rec["created_at"]}
    for f in ENTITY_FIELDS.get(etype, []):
        out[f] = rec.get(f)
    if etype != "RecipeComponent":
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    return out


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# Invalid pagination params -> ERR_INVALID_REQUEST (422).
# ---------------------------------------------------------------------------
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100.")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer.")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0.")

    return limit, offset


def paginate(records):
    """Sort by created_at ASC (PRD §2.3), tiebreak by creation sequence,
    apply limit/offset, and return (page_items_serialized, limit, offset,
    total_count)."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serialize(r) for r in page], limit, offset, total


# ---------------------------------------------------------------------------
# FK / path existence resolution (priority 3: ERR_NOT_FOUND).
# ---------------------------------------------------------------------------
def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise errors.not_found()
    return rec
