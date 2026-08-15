"""Inventory programs (PRD §3.6): lifecycle, locked pricing pin, replenishment."""
from flask import Blueprint

import db
import errors
from errors import ApiError
from middleware import get_auth_context, require_role
from response import success_object
from services.calculations import select_locked_cut_program
from services.common import (
    body, get_or_404, get_single, list_many, owner_of_inventory_program, pub,
    req_enum, req_int, req_str, stamp_new, touch,
)
from services.workflows import suspend_inventory_program

bp = Blueprint("inventory_programs", __name__)

PRICING_MODES = ("LOCKED", "CURRENT")


@bp.route("/inventory-programs", methods=["POST"])
def create_inventory_program():
    user_id, role = get_auth_context()
    require_role(role, ("SalesEngineer",))
    data = body()
    customer_id = req_str(data, "customer_id")
    package_spec_id = req_str(data, "package_spec_id")
    pricing_mode = req_enum(data, "pricing_mode", PRICING_MODES)
    max_stock = req_int(data, "max_stock_qty", minimum=1)
    reorder_point = req_int(data, "reorder_point_qty", minimum=0)
    min_release = req_int(data, "min_release_qty", minimum=1)
    # Existence, left to right; then the customer/spec ownership agreement
    # check that this step additionally requires (PRD §2.5 step 5).
    get_or_404(db.customers, customer_id, "Customer")
    spec = get_or_404(db.package_specs, package_spec_id, "PackageSpec")
    if customer_id != spec["customer_id"]:
        raise ApiError(
            errors.ERR_INVALID_REQUEST,
            "program customer_id must equal the spec's owning customer_id",
            400,
        )
    if spec["status"] != "APPROVED":
        raise ApiError(
            errors.ERR_SPEC_NOT_APPROVED,
            "Inventory programs require an APPROVED package spec",
            409,
        )
    rec = stamp_new({
        "customer_id": customer_id,
        "package_spec_id": package_spec_id,
        "pricing_mode": pricing_mode,
        "max_stock_qty": max_stock,
        "reorder_point_qty": reorder_point,
        "min_release_qty": min_release,
        "locked_material_cost_bf_cents": None,
        "status": "PROPOSED",
        "produced_qty": 0,
        "on_hand_qty": 0,
        "reserved_qty": 0,
        "shipped_qty": 0,
    })
    db.inventory_programs[rec["id"]] = rec
    return success_object(pub(rec), 201)


@bp.route("/inventory-programs", methods=["GET"])
def list_inventory_programs():
    return list_many(
        db.inventory_programs, owner_of_inventory_program,
        ("customer_id", "package_spec_id", "status"),
    )


@bp.route("/inventory-programs/<rid>", methods=["GET"])
def get_inventory_program(rid):
    return get_single(db.inventory_programs, rid, owner_of_inventory_program, "InventoryProgram")


@bp.route("/inventory-programs/<rid>/activate", methods=["POST"])
def activate_inventory_program(rid):
    user_id, role = get_auth_context()
    require_role(role, ("SalesEngineer",))
    rec = get_or_404(db.inventory_programs, rid, "InventoryProgram")
    if rec["status"] != "PROPOSED":
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot activate a program in {rec['status']}", 409)
    if rec["pricing_mode"] == "LOCKED":
        # Version pinning: material cost pinned at activation; later edits never move it.
        spec = db.package_specs.get(rec["package_spec_id"])
        material = db.materials.get(spec["material_id"]) if spec else None
        rec["locked_material_cost_bf_cents"] = material["cost_per_board_ft_cents"] if material else None
    rec["status"] = "ACTIVE"
    touch(rec)
    return success_object(pub(rec))


@bp.route("/inventory-programs/<rid>/suspend", methods=["POST"])
def suspend_inventory_program_route(rid):
    user_id, role = get_auth_context()
    require_role(role, ("SalesEngineer",))
    rec = get_or_404(db.inventory_programs, rid, "InventoryProgram")
    if rec["status"] != "ACTIVE":
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot suspend a program in {rec['status']}", 409)
    suspend_inventory_program(rec)
    return success_object(pub(rec))


@bp.route("/inventory-programs/<rid>/resume", methods=["POST"])
def resume_inventory_program(rid):
    user_id, role = get_auth_context()
    require_role(role, ("SalesEngineer",))
    rec = get_or_404(db.inventory_programs, rid, "InventoryProgram")
    if rec["status"] != "SUSPENDED":
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot resume a program in {rec['status']}", 409)
    rec["status"] = "ACTIVE"
    touch(rec)
    return success_object(pub(rec))


@bp.route("/inventory-programs/<rid>/close", methods=["POST"])
def close_inventory_program(rid):
    user_id, role = get_auth_context()
    require_role(role, ("SalesEngineer",))
    rec = get_or_404(db.inventory_programs, rid, "InventoryProgram")
    if rec["status"] not in ("PROPOSED", "ACTIVE", "SUSPENDED"):
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot close a program in {rec['status']}", 409)
    open_releases = any(
        r["inventory_program_id"] == rec["id"] and r["status"] in ("PENDING", "ALLOCATED")
        for r in db.release_orders.values()
    )
    if open_releases:
        raise ApiError(
            errors.ERR_PROGRAM_HAS_OPEN_RELEASES,
            "Program close is blocked by PENDING or ALLOCATED release orders",
            409,
        )
    rec["status"] = "CLOSED"
    touch(rec)
    return success_object(pub(rec))


@bp.route("/inventory-programs/<rid>/replenish", methods=["POST"])
def replenish_inventory_program(rid):
    from routes.production_orders import new_order_record

    user_id, role = get_auth_context()
    require_role(role, ("PlantManager",))
    data = body()
    qty = req_int(data, "qty", minimum=1)
    rec = get_or_404(db.inventory_programs, rid, "InventoryProgram")
    if rec["status"] != "ACTIVE":
        raise ApiError(errors.ERR_PROGRAM_NOT_ACTIVE, "Replenishment requires an ACTIVE program", 409)
    program = select_locked_cut_program(rec["package_spec_id"])
    if program is None:
        raise ApiError(
            errors.ERR_NO_LOCKED_PROGRAM,
            "No LOCKED cut program exists for the program's package spec",
            409,
        )
    order = new_order_record(rec["package_spec_id"], program["id"], qty, "REPLENISHMENT", rec["id"])
    db.production_orders[order["id"]] = order
    return success_object(pub(order), 201)
