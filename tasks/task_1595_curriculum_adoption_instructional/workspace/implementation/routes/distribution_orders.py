"""DistributionOrder endpoints (PRD §3.7): request, approve (freeze check
before the inventory check), backorder, ship, receive, cancel."""

from flask import Blueprint, request

import serializers
from db import bump, new_id, refresh, stamp_new, store
from errors import (ERR_INSUFFICIENT_INVENTORY, ERR_MATERIAL_FROZEN,
                    ERR_MATERIAL_NOT_ADOPTED, conflict, invalid_state)
from middleware import (ALL_ROLES, auth_context, get_body, get_or_404, req_enum,
                        req_int, req_str, require_roles)
from response import paginate, sort_created, success_object
from services.calculations import (lot_available_units,
                                   recompute_open_backorder_count)

bp = Blueprint("distribution_orders", __name__)


def _get_do(do_id):
    return get_or_404(store.distribution_orders, do_id, "DistributionOrder")


def _cycle_for(do):
    material = store.materials.get(do["material_id"])
    if material is None:
        return None
    return store.cycles.get(material["cycle_id"])


@bp.route("/distribution-orders", methods=["POST"])
def create_distribution_order():
    user_id, role = auth_context()
    require_roles(role, ("WarehouseManager",))
    body = get_body()
    # Tier 3 body FK resolution precedes the remaining shape checks.
    material = None
    raw_material_id = body.get("material_id")
    if isinstance(raw_material_id, str) and raw_material_id:
        material = get_or_404(store.materials, raw_material_id,
                              "InstructionalMaterial")
    school_code = req_str(body, "school_code")
    classroom_label = req_str(body, "classroom_label")
    quantity = req_int(body, "quantity", minimum=1)
    need_priority = req_int(body, "need_priority", minimum=1, maximum=5)
    material_id = req_str(body, "material_id")
    if material is None:
        material = get_or_404(store.materials, material_id,
                              "InstructionalMaterial")
    # Tier 9 safety (frozen) runs before tier 11 referential (adopted).
    if material["availability_status"] != "USABLE":
        raise conflict(ERR_MATERIAL_FROZEN,
                       "the material is frozen by an open challenge")
    if material["adoption_status"] != "ADOPTED":
        raise conflict(ERR_MATERIAL_NOT_ADOPTED,
                       "distribution exists only for adopted materials")
    do = {
        "id": new_id(),
        "material_id": material["id"],
        "school_code": school_code,
        "classroom_label": classroom_label,
        "quantity": quantity,
        "need_priority": need_priority,
        "status": "REQUESTED",
    }
    stamp_new(do)
    store.distribution_orders[do["id"]] = do
    return success_object(serializers.distribution_order(do), status=201)


@bp.route("/distribution-orders", methods=["GET"])
def list_distribution_orders():
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    items = list(store.distribution_orders.values())
    material_id = request.args.get("material_id")
    school_code = request.args.get("school_code")
    status = request.args.get("status")
    if material_id is not None:
        items = [d for d in items if d["material_id"] == material_id]
    if school_code is not None:
        items = [d for d in items if d["school_code"] == school_code]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return paginate(sort_created(items), serializers.distribution_order)


@bp.route("/distribution-orders/<doId>/transitions", methods=["POST"])
def distribution_order_transition(doId):
    user_id, role = auth_context()
    require_roles(role, ("WarehouseManager",))
    do = _get_do(doId)
    body = get_body()
    to_state = req_enum(body, "to_state",
                        ("APPROVED", "BACKORDERED", "SHIPPED", "RECEIVED",
                         "CANCELLED"))
    status = do["status"]

    if to_state == "APPROVED":
        if status not in ("REQUESTED", "BACKORDERED"):
            raise invalid_state("only a REQUESTED or BACKORDERED order may be "
                                "approved")
        material = store.materials.get(do["material_id"])
        # The freeze check runs before the inventory check (PRD §3.7).
        if material is None or material["availability_status"] != "USABLE":
            raise conflict(ERR_MATERIAL_FROZEN,
                           "the material is frozen by an open challenge")
        lot = store.inventory_lots.get(do["material_id"])
        available = lot_available_units(lot) if lot is not None else 0
        if available < do["quantity"]:
            raise conflict(ERR_INSUFFICIENT_INVENTORY,
                           "available units do not cover the requested quantity")
    elif to_state == "BACKORDERED":
        if status != "REQUESTED":
            raise invalid_state("only a REQUESTED order may be backordered")
    elif to_state == "SHIPPED":
        if status != "APPROVED":
            raise invalid_state("only an APPROVED order may be shipped")
    elif to_state == "RECEIVED":
        if status != "SHIPPED":
            raise invalid_state("only a SHIPPED order may be received")
    elif to_state == "CANCELLED":
        if status not in ("REQUESTED", "APPROVED", "BACKORDERED"):
            raise invalid_state("only a REQUESTED, APPROVED, or BACKORDERED "
                                "order may be cancelled")

    # --- side effects -------------------------------------------------------
    if to_state == "SHIPPED":
        lot = store.inventory_lots.get(do["material_id"])
        if lot is not None:
            lot["on_hand_units"] -= do["quantity"]
            lot["in_transit_units"] += do["quantity"]
            refresh(lot)
    elif to_state == "RECEIVED":
        lot = store.inventory_lots.get(do["material_id"])
        if lot is not None:
            lot["in_transit_units"] -= do["quantity"]
            lot["delivered_units"] += do["quantity"]
            refresh(lot)
    # allocated_units is derived from APPROVED orders, so approve/cancel need
    # no stored lot writes — the derivation re-resolves on read (PRD §2.11).
    do["status"] = to_state
    bump(do)
    if to_state in ("APPROVED", "BACKORDERED", "CANCELLED"):
        cycle = _cycle_for(do)
        if cycle is not None:
            recompute_open_backorder_count(cycle)
    return success_object(serializers.distribution_order(do))
