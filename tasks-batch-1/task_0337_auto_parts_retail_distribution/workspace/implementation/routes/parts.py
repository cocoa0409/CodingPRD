"""Part catalog + inventory endpoints."""
from __future__ import annotations

from flask import Blueprint

from db import db
from errors import (
    conflict,
    APIError,
    ERR_DUPLICATE_SKU,
    ERR_CORE_CHARGE_INCONSISTENT,
    ERR_PART_ALREADY_DISCONTINUED,
    ERR_PART_HAS_RESERVATIONS,
)
from middleware import require_role, get_body
from response import success, list_success
from services import common as c
from services.inventory import increment_on_hand
from services.model import stamp_common, touch, serialize, get_part

bp = Blueprint("parts", __name__)


def _serialize_part(p: dict) -> dict:
    return serialize(p)


@bp.post("/parts")
def create_part():
    require_role("InventoryManager")
    body = get_body()

    sku = c.as_nonempty_string(body, "sku", required=True)
    description = c.as_string(body, "description", required=True)
    list_price_cents = c.as_int(body, "list_price_cents", required=True, min_value=1)
    cost_cents = c.as_int(body, "cost_cents", required=True, min_value=0)
    core_charge_cents = c.as_int(body, "core_charge_cents", required=False, default=0, min_value=0)
    is_rebuildable = c.as_bool(body, "is_rebuildable", required=False, default=False)
    warranty_days = c.as_int(body, "warranty_days", required=False, default=0, min_value=0)
    stockable = c.as_bool(body, "stockable", required=False, default=True)
    reorder_point = c.as_int(body, "reorder_point", required=False, default=0, min_value=0)
    reorder_qty = c.as_int(body, "reorder_qty", required=False, default=0, min_value=0)

    # priority 5: duplicate sku
    for existing in db.parts.values():
        if existing["sku"] == sku:
            raise conflict(ERR_DUPLICATE_SKU)

    # priority 10: core charge consistency
    if is_rebuildable and core_charge_cents <= 0:
        raise APIError(ERR_CORE_CHARGE_INCONSISTENT, 422)
    if not is_rebuildable and core_charge_cents != 0:
        raise APIError(ERR_CORE_CHARGE_INCONSISTENT, 422)

    part = {
        "sku": sku,
        "description": description,
        "list_price_cents": list_price_cents,
        "cost_cents": cost_cents,
        "core_charge_cents": core_charge_cents,
        "is_rebuildable": is_rebuildable,
        "warranty_days": warranty_days,
        "stockable": stockable,
        "on_hand_qty": 0,
        "reserved_qty": 0,
        "available_qty": 0,
        "reorder_point": reorder_point,
        "reorder_qty": reorder_qty,
        "status": "ACTIVE",
    }
    stamp_common(part)
    db.parts[part["id"]] = part
    return success(_serialize_part(part), 201)


@bp.get("/parts")
def list_parts():
    require_role("CounterClerk", "WholesaleRep", "InventoryManager", "WarrantyAdmin")
    limit, offset = c.parse_pagination()
    from flask import request

    sku = request.args.get("sku")
    status = request.args.get("status")
    filters = []
    if sku is not None:
        filters.append(lambda p: p["sku"] == sku)
    if status is not None:
        filters.append(lambda p: p["status"] == status)
    page, total = c.paginate(db.parts.values(), limit, offset, filters)
    return list_success([_serialize_part(p) for p in page], limit, offset, total)


@bp.get("/parts/<pid>")
def get_one_part(pid):
    require_role("CounterClerk", "WholesaleRep", "InventoryManager", "WarrantyAdmin")
    part = get_part(pid)
    return success(_serialize_part(part))


@bp.post("/parts/<pid>/receive-stock")
def receive_stock(pid):
    require_role("InventoryManager")
    part = get_part(pid)
    body = get_body()
    qty = c.as_int(body, "qty", required=True, min_value=1)
    increment_on_hand(part, qty)
    return success(_serialize_part(part))


@bp.post("/parts/<pid>/discontinue")
def discontinue_part(pid):
    require_role("InventoryManager")
    part = get_part(pid)
    # precondition: ACTIVE
    if part["status"] != "ACTIVE":
        raise conflict(ERR_PART_ALREADY_DISCONTINUED)
    # precondition: no reservations
    if part["reserved_qty"] != 0:
        raise conflict(ERR_PART_HAS_RESERVATIONS)
    # cascade: SUGGESTED/ORDERED reorder requests -> CANCELLED
    for ro in db.reorder_requests.values():
        if ro["part_id"] == part["id"] and ro["status"] in ("SUGGESTED", "ORDERED"):
            ro["status"] = "CANCELLED"
            touch(ro)
    part["status"] = "DISCONTINUED"
    touch(part)
    return success(_serialize_part(part))
