"""InventoryItem (catalog) endpoints."""
from flask import Blueprint, request

import errors
from db import db, base_fields, public
from middleware import get_identity, require_role
from response import success, list_success
from validation import (get_json_body, require_str, require_int, require_enum,
                        optional_int, parse_pagination, paginate)

bp = Blueprint("inventory", __name__)

CATEGORIES = {"TREE", "WREATH", "GARLAND", "LIGHTING"}


def _get_item_or_404(item_id):
    rec = db.inventory_items.get(item_id)
    if rec is None:
        raise errors.not_found("Inventory item not found")
    return rec


@bp.post("/inventory-items")
def create_inventory_item():
    _, role = get_identity()
    require_role(role, ["PlatformAdmin"])
    body = get_json_body()
    sku = require_str(body, "sku")
    category = require_enum(body, "category", CATEGORIES)
    unit_replacement_cents = require_int(body, "unit_replacement_cents", minimum=0)
    reorder_threshold = optional_int(body, "reorder_threshold", default=0, minimum=0)
    on_hand_qty = optional_int(body, "on_hand_qty", default=0, minimum=0)

    # SKU uniqueness (priority 16)
    if any(it["sku"] == sku for it in db.inventory_items.values()):
        raise errors.duplicate_code("SKU already exists")

    rec = base_fields()
    rec.update({
        "sku": sku,
        "category": category,
        "unit_replacement_cents": unit_replacement_cents,
        "on_hand_qty": on_hand_qty,
        "reorder_threshold": reorder_threshold,
    })
    db.inventory_items[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/inventory-items/<id>")
def get_inventory_item(id):
    _, role = get_identity()
    require_role(role, ["AccountManager", "FieldSupervisor", "PlatformAdmin"])
    rec = _get_item_or_404(id)
    return success(public(rec))


@bp.get("/inventory-items")
def list_inventory_items():
    _, role = get_identity()
    require_role(role, ["AccountManager", "FieldSupervisor", "PlatformAdmin"])
    limit, offset = parse_pagination()
    category = request.args.get("category")
    records = list(db.inventory_items.values())
    if category is not None:
        records = [r for r in records if r["category"] == category]
    page, total = paginate(records, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


@bp.get("/inventory-items/<id>/proposal-line-items")
def list_item_line_items(id):
    _, role = get_identity()
    require_role(role, ["AccountManager", "FieldSupervisor", "PlatformAdmin"])
    _get_item_or_404(id)
    limit, offset = parse_pagination()
    records = [li for li in db.proposal_line_items.values() if li["inventory_item_id"] == id]
    page, total = paginate(records, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)
