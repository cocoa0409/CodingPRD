"""Production orders: quoting, confirmation, fabrication, quality holds
(PRD §3.5). fab_status and quality_hold are independent parallel state
dimensions on the same row."""
from flask import Blueprint

import db
import errors
from errors import ApiError
from middleware import get_auth_context, require_role
from response import success_object
from services.calculations import (
    final_pricing, in_service_tooling, provisional_pricing,
)
from services.common import (
    body, get_or_404, get_single, list_many, owner_of_production_order,
    parse_iso_datetime, pub, req_datetime, req_int, req_str, stamp_new, touch,
)
from services.workflows import cancel_production_order

bp = Blueprint("production_orders", __name__)


def new_order_record(package_spec_id, cut_program_id, qty, order_kind, inventory_program_id=None):
    """Shared creation path for CUSTOMER and REPLENISHMENT orders (both are
    born QUOTED with provisional pricing)."""
    spec = db.package_specs.get(package_spec_id)
    material = db.materials.get(spec["material_id"]) if spec else None
    program = db.cut_programs.get(cut_program_id)
    rec = {
        "package_spec_id": package_spec_id,
        "cut_program_id": cut_program_id,
        "inventory_program_id": inventory_program_id,
        "order_kind": order_kind,
        "qty": qty,
        "provisional_unit_price_cents": None,
        "provisional_total_cents": None,
        "final_unit_price_cents": None,
        "final_total_cents": None,
        "tooling_amort_cents": None,  # determined at confirmation
        "machine_id": None,
        "window_start": None,
        "window_end": None,
        "fab_status": "QUOTED",
        "quality_hold": "NONE",
    }
    if spec is not None and material is not None and program is not None:
        unit, total = provisional_pricing(spec, material, program, qty)
        rec["provisional_unit_price_cents"] = unit
        rec["provisional_total_cents"] = total
    return stamp_new(rec)


def _machine_window_conflict(machine_id, start_dt, end_dt, exclude_order_id=None):
    """Half-open [start, end) overlap against every non-CANCELLED order's
    window on the same machine; mere adjacency (end == start) is allowed."""
    for other in db.production_orders.values():
        if other["id"] == exclude_order_id:
            continue
        if other.get("machine_id") != machine_id or other["fab_status"] == "CANCELLED":
            continue
        if not other.get("window_start") or not other.get("window_end"):
            continue
        os_ = parse_iso_datetime(other["window_start"], "window_start")
        oe = parse_iso_datetime(other["window_end"], "window_end")
        if start_dt < oe and os_ < end_dt:
            return True
    return False


@bp.route("/production-orders", methods=["POST"])
def create_production_order():
    user_id, role = get_auth_context()
    require_role(role, ("SalesEngineer",))
    data = body()
    package_spec_id = req_str(data, "package_spec_id")
    cut_program_id = req_str(data, "cut_program_id")
    qty = req_int(data, "qty", minimum=1)
    get_or_404(db.package_specs, package_spec_id, "PackageSpec")
    program = get_or_404(db.cut_programs, cut_program_id, "CutProgram")
    if program["status"] not in ("NESTED", "LOCKED"):
        raise ApiError(
            errors.ERR_INVALID_STATE,
            f"Cut program must be NESTED or LOCKED, got {program['status']}",
            409,
        )
    rec = new_order_record(package_spec_id, cut_program_id, qty, "CUSTOMER")
    db.production_orders[rec["id"]] = rec
    return success_object(pub(rec), 201)


@bp.route("/production-orders", methods=["GET"])
def list_production_orders():
    return list_many(
        db.production_orders, owner_of_production_order,
        ("package_spec_id", "cut_program_id", "inventory_program_id", "fab_status"),
    )


@bp.route("/production-orders/<rid>", methods=["GET"])
def get_production_order(rid):
    return get_single(db.production_orders, rid, owner_of_production_order, "ProductionOrder")


@bp.route("/production-orders/<rid>/confirm", methods=["POST"])
def confirm_production_order(rid):
    user_id, role = get_auth_context()
    require_role(role, ("SalesEngineer",))
    data = body()
    machine_id = req_str(data, "machine_id")
    window_start = req_datetime(data, "window_start")
    window_end = req_datetime(data, "window_end")

    order = get_or_404(db.production_orders, rid, "ProductionOrder")
    if order["fab_status"] != "QUOTED":
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot confirm an order in {order['fab_status']}", 409)
    spec = db.package_specs.get(order["package_spec_id"])
    if spec is None or spec["status"] != "APPROVED":
        raise ApiError(errors.ERR_SPEC_NOT_APPROVED, "Confirmation requires an APPROVED package spec", 409)
    program = db.cut_programs.get(order["cut_program_id"])
    if program is None or program["status"] != "LOCKED":
        raise ApiError(errors.ERR_INVALID_STATE, "Confirmation requires a LOCKED cut program", 409)
    tooling = None
    if program["method"] == "DIE_CUT":
        tooling = in_service_tooling(program["id"])
        if tooling is None:
            raise ApiError(
                errors.ERR_TOOLING_NOT_IN_SERVICE,
                "Confirmation requires the linked tooling to be IN_SERVICE",
                409,
            )
    start_dt = parse_iso_datetime(window_start, "window_start")
    end_dt = parse_iso_datetime(window_end, "window_end")
    if not start_dt < end_dt:
        raise ApiError(errors.ERR_INVALID_REQUEST, "window_start must be before window_end", 400)
    if _machine_window_conflict(machine_id, start_dt, end_dt):
        raise ApiError(
            errors.ERR_MACHINE_WINDOW_CONFLICT,
            "Machine window overlaps another non-CANCELLED order's window on this machine",
            409,
        )
    material = db.materials.get(spec["material_id"])
    unit, total, charge = final_pricing(order, material, program, tooling)
    order["final_unit_price_cents"] = unit
    order["final_total_cents"] = total
    order["tooling_amort_cents"] = charge  # 0 for CNC_ROUTE work
    order["machine_id"] = machine_id
    order["window_start"] = window_start
    order["window_end"] = window_end
    order["fab_status"] = "CONFIRMED"
    order["_tooling_id"] = tooling["id"] if tooling is not None else None
    if tooling is not None and charge:
        tooling["amortized_cents"] += charge
        touch(tooling)
    touch(order)
    return success_object(pub(order))


@bp.route("/production-orders/<rid>/start", methods=["POST"])
def start_production_order(rid):
    user_id, role = get_auth_context()
    require_role(role, ("PlantManager",))
    order = get_or_404(db.production_orders, rid, "ProductionOrder")
    if order["fab_status"] != "CONFIRMED":
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot start an order in {order['fab_status']}", 409)
    order["fab_status"] = "IN_PROGRESS"
    touch(order)
    return success_object(pub(order))


@bp.route("/production-orders/<rid>/complete", methods=["POST"])
def complete_production_order(rid):
    user_id, role = get_auth_context()
    require_role(role, ("PlantManager",))
    order = get_or_404(db.production_orders, rid, "ProductionOrder")
    if order["fab_status"] != "IN_PROGRESS":
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot complete an order in {order['fab_status']}", 409)
    if order["quality_hold"] != "NONE":
        raise ApiError(errors.ERR_INVALID_STATE, "Cannot complete while a quality hold is in effect", 409)
    order["fab_status"] = "COMPLETED"
    if order["order_kind"] == "REPLENISHMENT" and order.get("inventory_program_id"):
        program = db.inventory_programs.get(order["inventory_program_id"])
        if program is not None:
            program["produced_qty"] += order["qty"]
            program["on_hand_qty"] += order["qty"]
            touch(program)
    touch(order)
    return success_object(pub(order))


@bp.route("/production-orders/<rid>/cancel", methods=["POST"])
def cancel_order_route(rid):
    user_id, role = get_auth_context()
    require_role(role, ("SalesEngineer",))
    order = get_or_404(db.production_orders, rid, "ProductionOrder")
    if order["fab_status"] not in ("QUOTED", "CONFIRMED"):
        raise ApiError(errors.ERR_INVALID_STATE, f"Cannot cancel an order in {order['fab_status']}", 409)
    cancel_production_order(order)
    return success_object(pub(order))


@bp.route("/production-orders/<rid>/hold", methods=["POST"])
def hold_production_order(rid):
    user_id, role = get_auth_context()
    require_role(role, ("QualityEngineer",))
    order = get_or_404(db.production_orders, rid, "ProductionOrder")
    if order["quality_hold"] != "NONE" or order["fab_status"] not in ("CONFIRMED", "IN_PROGRESS"):
        raise ApiError(
            errors.ERR_INVALID_STATE,
            "A quality hold requires fab_status CONFIRMED or IN_PROGRESS and quality_hold NONE",
            409,
        )
    order["quality_hold"] = "ON_HOLD"
    touch(order)
    return success_object(pub(order))


@bp.route("/production-orders/<rid>/release-hold", methods=["POST"])
def release_hold_production_order(rid):
    user_id, role = get_auth_context()
    require_role(role, ("QualityEngineer",))
    order = get_or_404(db.production_orders, rid, "ProductionOrder")
    if order["quality_hold"] != "ON_HOLD":
        raise ApiError(errors.ERR_INVALID_STATE, "No quality hold is in effect", 409)
    order["quality_hold"] = "NONE"
    touch(order)
    return success_object(pub(order))
