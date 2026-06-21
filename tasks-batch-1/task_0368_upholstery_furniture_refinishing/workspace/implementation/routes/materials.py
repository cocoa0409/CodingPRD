"""Material orders: place / receive / cancel, list/fetch."""
from flask import Blueprint, request

from db import db
from errors import err
import errors
from middleware import get_identity, require_roles
from helpers import (base_record, get_body, require_string, require_int,
                     optional_number, get_resource_or_404, get_fk_or_404,
                     parse_pagination, paginate, touch, serialize, serialize_list)
from response import ok_object, ok_array
import calculations as calc
from services import reconcile_materials_committed, reconcile_balance_due

bp = Blueprint("materials", __name__)


@bp.post("/material-orders")
def create_material_order():
    _, role = get_identity()
    require_roles(role, {"ShopManager"})
    body = get_body()
    work_order_id = require_string(body, "work_order_id")
    fabric_sku_id = body.get("fabric_sku_id")
    foam_spec_id = body.get("foam_spec_id")
    if fabric_sku_id is not None and not isinstance(fabric_sku_id, str):
        raise err(errors.ERR_INVALID_REQUEST, "fabric_sku_id must be a string")
    if foam_spec_id is not None and not isinstance(foam_spec_id, str):
        raise err(errors.ERR_INVALID_REQUEST, "foam_spec_id must be a string")
    yards_ordered = optional_number(body, "yards_ordered", 0)
    board_feet_ordered = optional_number(body, "board_feet_ordered", 0)
    if yards_ordered < 0 or board_feet_ordered < 0:
        raise err(errors.ERR_INVALID_REQUEST, "yards/board_feet may not be negative")

    # FK existence (priority 12).
    get_fk_or_404(db.work_orders, work_order_id)
    if fabric_sku_id is not None:
        get_fk_or_404(db.fabric_skus, fabric_sku_id)
    if foam_spec_id is not None:
        get_fk_or_404(db.foam_specs, foam_spec_id)

    # Catalog availability (priority 31): DISCONTINUED rejected.
    if fabric_sku_id is not None:
        sku = db.fabric_skus[fabric_sku_id]
        if sku["status"] != "LISTED":
            raise err(errors.ERR_CATALOG_ITEM_UNAVAILABLE, "Fabric SKU is not LISTED")
    if foam_spec_id is not None:
        spec = db.foam_specs[foam_spec_id]
        if spec["status"] != "LISTED":
            raise err(errors.ERR_CATALOG_ITEM_UNAVAILABLE, "Foam spec is not LISTED")

    fabric_price = db.fabric_skus[fabric_sku_id]["price_cents_per_yard"] \
        if fabric_sku_id else 0
    foam_price = db.foam_specs[foam_spec_id]["price_cents_per_board_foot"] \
        if foam_spec_id else 0
    provisional = calc.provisional_cost(
        yards_ordered, fabric_price, board_feet_ordered, foam_price)

    rec = base_record(common=True)
    rec.update({
        "work_order_id": work_order_id,
        "fabric_sku_id": fabric_sku_id,
        "foam_spec_id": foam_spec_id,
        "yards_ordered": yards_ordered,
        "board_feet_ordered": board_feet_ordered,
        "provisional_cost_cents": provisional,
        "finalized_cost_cents": 0,
        "received_fabric_price_cents_per_yard": 0,
        "received_foam_price_cents_per_board_foot": 0,
        "status": "ORDERED",
        "_reserved_yards": 0,
    })

    # Reserve yards from on-hand stock; debit in_stock_yards (PRD §3.5).
    if fabric_sku_id is not None and yards_ordered > 0:
        sku = db.fabric_skus[fabric_sku_id]
        sku["in_stock_yards"] = sku["in_stock_yards"] - yards_ordered
        touch(sku)
        rec["_reserved_yards"] = yards_ordered

    db.material_orders[rec["id"]] = rec

    wo = db.work_orders[work_order_id]
    reconcile_materials_committed(wo)
    touch(wo)
    return ok_object(serialize(rec), 201)


@bp.get("/material-orders/<mid>")
def get_material_order(mid):
    _, role = get_identity()
    require_roles(role, {"ShopManager", "Estimator"})
    rec = get_resource_or_404(db.material_orders, mid)
    return ok_object(serialize(rec), 200)


@bp.get("/material-orders")
def list_material_orders():
    _, role = get_identity()
    require_roles(role, {"ShopManager", "Estimator"})
    limit, offset = parse_pagination()
    work_order_id = request.args.get("work_order_id")
    fabric_sku_id = request.args.get("fabric_sku_id")
    foam_spec_id = request.args.get("foam_spec_id")
    status = request.args.get("status")
    matches = list(db.material_orders.values())
    if work_order_id is not None:
        matches = [m for m in matches if m["work_order_id"] == work_order_id]
    if fabric_sku_id is not None:
        matches = [m for m in matches if m.get("fabric_sku_id") == fabric_sku_id]
    if foam_spec_id is not None:
        matches = [m for m in matches if m.get("foam_spec_id") == foam_spec_id]
    if status is not None:
        matches = [m for m in matches if m["status"] == status]
    page, total = paginate(matches, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.post("/material-orders/<mid>/receive")
def receive_material_order(mid):
    _, role = get_identity()
    require_roles(role, {"ShopManager"})
    rec = get_resource_or_404(db.material_orders, mid)
    body = get_body()
    recv_fabric = body.get("received_fabric_price_cents_per_yard", 0)
    recv_foam = body.get("received_foam_price_cents_per_board_foot", 0)
    if recv_fabric is None:
        recv_fabric = 0
    if recv_foam is None:
        recv_foam = 0
    if isinstance(recv_fabric, bool) or not isinstance(recv_fabric, int):
        raise err(errors.ERR_INVALID_REQUEST,
                  "received_fabric_price_cents_per_yard must be an integer")
    if isinstance(recv_foam, bool) or not isinstance(recv_foam, int):
        raise err(errors.ERR_INVALID_REQUEST,
                  "received_foam_price_cents_per_board_foot must be an integer")

    if rec["status"] != "ORDERED":
        raise err(errors.ERR_INVALID_STATE, "Material order is not ORDERED")
    wo = db.work_orders.get(rec["work_order_id"])
    if wo is None or wo["status"] not in ("APPROVED", "IN_PRODUCTION"):
        raise err(errors.ERR_INVALID_STATE,
                  "Parent work order must be APPROVED or IN_PRODUCTION")

    rec["received_fabric_price_cents_per_yard"] = recv_fabric
    rec["received_foam_price_cents_per_board_foot"] = recv_foam
    rec["finalized_cost_cents"] = calc.finalized_cost(
        rec["yards_ordered"], recv_fabric, rec["board_feet_ordered"], recv_foam)
    rec["status"] = "RECEIVED"
    touch(rec)

    reconcile_materials_committed(wo)
    touch(wo)
    return ok_object(serialize(rec), 200)


@bp.post("/material-orders/<mid>/cancel")
def cancel_material_order(mid):
    _, role = get_identity()
    require_roles(role, {"ShopManager"})
    rec = get_resource_or_404(db.material_orders, mid)
    if rec["status"] != "ORDERED":
        raise err(errors.ERR_INVALID_STATE, "Material order is not ORDERED")

    # Return reserved fabric yards (yard-conservation invariant).
    reserved = rec.get("_reserved_yards", 0)
    if reserved and rec.get("fabric_sku_id"):
        sku = db.fabric_skus.get(rec["fabric_sku_id"])
        if sku is not None:
            sku["in_stock_yards"] = sku["in_stock_yards"] + reserved
            touch(sku)
    rec["_reserved_yards"] = 0
    rec["status"] = "CANCELLED"
    touch(rec)

    wo = db.work_orders.get(rec["work_order_id"])
    if wo is not None:
        reconcile_materials_committed(wo)
        touch(wo)
    return ok_object(serialize(rec), 200)
