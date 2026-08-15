"""Release orders (PRD §3.6): allocation pricing, reservation bookkeeping,
shipment-triggered auto-replenishment."""
from flask import Blueprint

import db
import errors
from errors import ApiError
from middleware import get_auth_context, require_role, forbid_unless_owner
from response import success_object
from services.calculations import release_pricing, select_locked_cut_program
from services.common import (
    body, get_or_404, get_single, list_many, owner_of_release_order, pub,
    req_datetime, req_int, req_str, stamp_new, touch,
)
from services.workflows import cancel_release_order

bp = Blueprint("release_orders", __name__)


def _run_replenishment_check(program):
    """replenishment_calc: after a ship, on_hand strictly below the reorder
    point spawns a REPLENISHMENT order for max_stock - on_hand - pipeline,
    when positive. Landing exactly on the reorder point triggers nothing."""
    if program["on_hand_qty"] >= program["reorder_point_qty"]:
        return
    pipeline_qty = sum(
        o["qty"]
        for o in db.production_orders.values()
        if o.get("inventory_program_id") == program["id"]
        and o["fab_status"] in ("QUOTED", "CONFIRMED", "IN_PROGRESS")
    )
    suggested = program["max_stock_qty"] - program["on_hand_qty"] - pipeline_qty
    if suggested <= 0:
        return
    program_rec = select_locked_cut_program(program["package_spec_id"])
    if program_rec is None:
        return  # no locked cut program to build against; the ship itself stands
    from routes.production_orders import new_order_record
    order = new_order_record(
        program["package_spec_id"], program_rec["id"], suggested, "REPLENISHMENT", program["id"]
    )
    db.production_orders[order["id"]] = order


@bp.route("/release-orders", methods=["POST"])
def create_release_order():
    user_id, role = get_auth_context()
    require_role(role, ("Customer",))
    data = body()
    inventory_program_id = req_str(data, "inventory_program_id")
    qty = req_int(data, "qty", minimum=1)
    ship_date = req_datetime(data, "requested_ship_date")
    program = get_or_404(db.inventory_programs, inventory_program_id, "InventoryProgram")
    forbid_unless_owner(role, user_id, program["customer_id"])
    if program["status"] != "ACTIVE":
        raise ApiError(errors.ERR_PROGRAM_NOT_ACTIVE, "Releases require an ACTIVE program", 409)
    if qty < program["min_release_qty"]:
        raise ApiError(
            errors.ERR_MIN_RELEASE_QTY,
            f"Release qty {qty} is below the program minimum of {program['min_release_qty']}",
            422,
        )
    rec = stamp_new({
        "inventory_program_id": inventory_program_id,
        "qty": qty,
        "requested_ship_date": ship_date,
        "unit_price_cents": None,
        "total_price_cents": None,
        "status": "PENDING",
    })
    db.release_orders[rec["id"]] = rec
    return success_object(pub(rec), 201)


@bp.route("/release-orders", methods=["GET"])
def list_release_orders():
    return list_many(db.release_orders, owner_of_release_order, ("inventory_program_id", "status"))


@bp.route("/release-orders/<rid>", methods=["GET"])
def get_release_order(rid):
    return get_single(db.release_orders, rid, owner_of_release_order, "ReleaseOrder")


@bp.route("/release-orders/<rid>/allocate", methods=["POST"])
def allocate_release_order(rid):
    user_id, role = get_auth_context()
    require_role(role, ("PlantManager",))
    rec = get_or_404(db.release_orders, rid, "ReleaseOrder")
    if rec["status"] != "PENDING":
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot allocate a release in {rec['status']}", 409)
    program = db.inventory_programs.get(rec["inventory_program_id"])
    if program is None or program["status"] != "ACTIVE":
        raise ApiError(errors.ERR_PROGRAM_NOT_ACTIVE, "Allocation requires an ACTIVE program", 409)
    spec = db.package_specs.get(program["package_spec_id"])
    material = db.materials.get(spec["material_id"]) if spec else None
    unit, total = release_pricing(rec, program, material)
    # Stock gate (last in the pipeline): equality with unreserved stock is allowed.
    if rec["qty"] > program["on_hand_qty"] - program["reserved_qty"]:
        raise ApiError(errors.ERR_INSUFFICIENT_STOCK, "Release qty exceeds unreserved stock", 409)
    rec["unit_price_cents"] = unit
    rec["total_price_cents"] = total
    rec["status"] = "ALLOCATED"
    program["reserved_qty"] += rec["qty"]
    touch(program)
    touch(rec)
    return success_object(pub(rec))


@bp.route("/release-orders/<rid>/deallocate", methods=["POST"])
def deallocate_release_order(rid):
    user_id, role = get_auth_context()
    require_role(role, ("PlantManager",))
    rec = get_or_404(db.release_orders, rid, "ReleaseOrder")
    if rec["status"] != "ALLOCATED":
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot deallocate a release in {rec['status']}", 409)
    program = db.inventory_programs.get(rec["inventory_program_id"])
    if program is not None:
        program["reserved_qty"] -= rec["qty"]
        touch(program)
    rec["unit_price_cents"] = None
    rec["total_price_cents"] = None
    rec["status"] = "PENDING"
    touch(rec)
    return success_object(pub(rec))


@bp.route("/release-orders/<rid>/ship", methods=["POST"])
def ship_release_order(rid):
    user_id, role = get_auth_context()
    require_role(role, ("PlantManager",))
    rec = get_or_404(db.release_orders, rid, "ReleaseOrder")
    if rec["status"] != "ALLOCATED":
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot ship a release in {rec['status']}", 409)
    program = db.inventory_programs.get(rec["inventory_program_id"])
    if program is None or program["status"] != "ACTIVE":
        raise ApiError(errors.ERR_PROGRAM_NOT_ACTIVE, "Shipping requires an ACTIVE program", 409)
    program["on_hand_qty"] -= rec["qty"]
    program["reserved_qty"] -= rec["qty"]
    program["shipped_qty"] += rec["qty"]
    rec["status"] = "SHIPPED"
    touch(rec)
    touch(program)
    _run_replenishment_check(program)
    return success_object(pub(rec))


@bp.route("/release-orders/<rid>/cancel", methods=["POST"])
def cancel_release_order_route(rid):
    user_id, role = get_auth_context()
    require_role(role, ("Customer", "PlantManager"))
    rec = get_or_404(db.release_orders, rid, "ReleaseOrder")
    program = db.inventory_programs.get(rec["inventory_program_id"])
    forbid_unless_owner(role, user_id, program["customer_id"] if program else None)
    if rec["status"] not in ("PENDING", "ALLOCATED"):
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot cancel a release in {rec['status']}", 409)
    cancel_release_order(rec)
    return success_object(pub(rec))
