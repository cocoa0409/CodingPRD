"""Kits: issue recording, line-side delivery, return (PRD 3.6)."""
from flask import Blueprint, request

from db import db, next_seq
from errors import (raise_error, ERR_INVALID_REQUEST, ERR_KIT_NOT_PICKING,
                    ERR_KIT_NOT_STAGED, ERR_CONSIGNED_SUBSTITUTION_FORBIDDEN,
                    ERR_COMPONENT_NOT_ON_DRAWING, ERR_CONSIGNED_LOT_NOT_ISSUABLE,
                    ERR_CONSIGNED_MPN_MISMATCH, ERR_CONSIGNED_INSUFFICIENT_ON_HAND,
                    ERR_KIT_LINE_OVER_ISSUE, ERR_MATERIAL_BUDGET_EXCEEDED)
from middleware import authenticate, ALL_ROLES
from response import success_object
from services import (ISSUE_SOURCES, common_fields, touch, kit_shortage_count,
                      recompute_order_spend, recompute_lot_liabilities,
                      lot_reconcile, return_kit, ser_kit, paginated)
from util import CLOCK
from validate import get_body, req_str, req_int, req_enum, require_path, require_fk

bp = Blueprint("kits", __name__)

MATERIALS_CLERK = {"MaterialsClerk"}


@bp.route("/plant/kits/<kid>", methods=["GET"])
def get_kit(kid):
    authenticate(ALL_ROLES)
    kit = require_path("kits", kid)
    return success_object(ser_kit(kit), 200)


@bp.route("/plant/kits", methods=["GET"])
def list_kits():
    authenticate(ALL_ROLES)
    items = list(db["kits"].values())
    build_order_id = request.args.get("build_order_id")
    if build_order_id is not None:
        items = [k for k in items if k["build_order_id"] == build_order_id]
    status = request.args.get("status")
    if status is not None:
        items = [k for k in items if k["status"] == status]
    return paginated(items, ser_kit)


@bp.route("/plant/kits/<kid>/issues", methods=["POST"])
def record_issue(kid):
    body = get_body()
    # Tier 1 (incl. conditional requirement: consigned issues carry a lot id).
    component_id = req_str(body, "component_id")
    qty_issued = req_int(body, "qty_issued", minimum=1)
    source = req_enum(body, "source", ISSUE_SOURCES)
    consigned_lot_id = body.get("consigned_lot_id")
    if source == "CONSIGNED_LOT":
        if consigned_lot_id is None or not isinstance(consigned_lot_id, str) \
                or consigned_lot_id.strip() == "":
            raise_error(ERR_INVALID_REQUEST,
                        "consigned_lot_id is required when source is CONSIGNED_LOT")
    elif consigned_lot_id is not None and not isinstance(consigned_lot_id, str):
        raise_error(ERR_INVALID_REQUEST, "invalid field type: consigned_lot_id")
    # Tiers 2-3
    authenticate(MATERIALS_CLERK)
    # Tier 4, left-to-right: path kit, then component_id, then consigned_lot_id.
    kit = require_path("kits", kid)
    component = require_fk("components", component_id, "component_id")
    lot = None
    if consigned_lot_id is not None:
        lot = require_fk("consigned_lots", consigned_lot_id, "consigned_lot_id")
    # Tier 6
    if kit["status"] != "PICKING":
        raise_error(ERR_KIT_NOT_PICKING, "issues may only be recorded into a PICKING kit")
    order = db["build_orders"][kit["build_order_id"]]
    # Tier 7: no substitution across the consigned/factory boundary.
    if component["supply_type"] == "CUSTOMER_CONSIGNED" and source != "CONSIGNED_LOT":
        raise_error(ERR_CONSIGNED_SUBSTITUTION_FORBIDDEN,
                    "a CUSTOMER_CONSIGNED BOM line may only be issued from a consigned lot")
    if component["supply_type"] == "FACTORY_STOCK" and source != "FACTORY_STOCK":
        raise_error(ERR_CONSIGNED_SUBSTITUTION_FORBIDDEN,
                    "a FACTORY_STOCK BOM line may only be issued from factory stock")
    # Tier 8
    if component["drawing_id"] != order["drawing_id"]:
        raise_error(ERR_COMPONENT_NOT_ON_DRAWING,
                    "issued component is not on the order's pinned drawing revision")
    if source == "CONSIGNED_LOT":
        if lot["status"] != "ACTIVE":
            raise_error(ERR_CONSIGNED_LOT_NOT_ISSUABLE,
                        "referenced lot is not ACTIVE")
        if lot["mpn"] != component["mpn"]:
            raise_error(ERR_CONSIGNED_MPN_MISMATCH,
                        "lot mpn differs from the BOM component mpn")
    # Tier 9
    if source == "CONSIGNED_LOT" and qty_issued > lot["qty_on_hand"]:
        raise_error(ERR_CONSIGNED_INSUFFICIENT_ON_HAND,
                    "qty_issued exceeds the lot's qty_on_hand")
    needed = component["qty_per_harness"] * order["qty_ordered"]
    issued_so_far = sum(iss["qty_issued"] for iss in kit["issues"]
                        if not iss["voided"] and iss["component_id"] == component["id"])
    if issued_so_far + qty_issued > needed:
        raise_error(ERR_KIT_LINE_OVER_ISSUE,
                    "cumulative non-voided issues exceed the line's needed quantity")
    # Tier 11: material budget (equality allowed; strictly greater rejected).
    if source == "CONSIGNED_LOT":
        snapshot = lot["unit_liability_cents"]
    else:
        snapshot = component["unit_cost_cents"]
    if order["material_budget_cents"] is not None:
        projected = order["material_spent_cents"] + qty_issued * snapshot
        if projected > order["material_budget_cents"]:
            raise_error(ERR_MATERIAL_BUDGET_EXCEEDED,
                        "issue would push material_spent_cents above material_budget_cents")

    issue = {
        "component_id": component["id"],
        "qty_issued": qty_issued,
        "source": source,
        "consigned_lot_id": lot["id"] if source == "CONSIGNED_LOT" else None,
        "unit_cost_snapshot_cents": snapshot,
        "issued_at": CLOCK.now(),
        "voided": False,
        "_delivered_qty": 0,
        "_seq": next_seq(),
    }
    kit["issues"].append(issue)

    if source == "CONSIGNED_LOT":
        lot["qty_on_hand"] -= qty_issued
        lot["qty_issued_open"] += qty_issued
        touch(lot)

    kit["shortage_count"] = kit_shortage_count(kit, order)
    if (kit["status"] == "PICKING" and kit["shortage_count"] == 0
            and any(not iss["voided"] for iss in kit["issues"])):
        kit["status"] = "STAGED"
    touch(kit)

    recompute_order_spend(order)
    touch(order)
    return success_object(ser_kit(kit), 201)


@bp.route("/plant/kits/<kid>/deliver", methods=["POST"])
def deliver_kit(kid):
    get_body()
    authenticate(MATERIALS_CLERK)
    kit = require_path("kits", kid)
    if kit["status"] != "STAGED":
        raise_error(ERR_KIT_NOT_STAGED, "only a STAGED kit may be delivered")

    order = db["build_orders"][kit["build_order_id"]]
    for iss in kit["issues"]:
        if iss["voided"] or iss["source"] != "CONSIGNED_LOT":
            continue
        lot = db["consigned_lots"].get(iss["consigned_lot_id"])
        if lot is None:
            continue
        lot["qty_issued_open"] -= iss["qty_issued"]
        lot["qty_consumed"] += iss["qty_issued"]
        iss["_delivered_qty"] = iss["qty_issued"]
        recompute_lot_liabilities(lot)
        lot_reconcile(lot)
        touch(lot)

    kit["status"] = "DELIVERED_LINESIDE"
    kit["delivered_at"] = CLOCK.now()
    touch(kit)

    # BuildOrder KITTING -> IN_BUILD on the order's first delivery.
    if order["status"] == "KITTING":
        order["status"] = "IN_BUILD"
        touch(order)
    return success_object(ser_kit(kit), 200)


@bp.route("/plant/kits/<kid>/return", methods=["POST"])
def return_kit_endpoint(kid):
    get_body()
    authenticate(MATERIALS_CLERK)
    kit = require_path("kits", kid)
    if kit["status"] not in ("PICKING", "STAGED"):
        raise_error(ERR_INVALID_REQUEST,
                    "only a PICKING or STAGED kit may be returned")
    return_kit(kit)
    return success_object(ser_kit(kit), 200)
