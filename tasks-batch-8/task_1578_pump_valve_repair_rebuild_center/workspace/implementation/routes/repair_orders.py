from flask import Blueprint, request

from db import DB, stamp_new, touch
from errors import (
    ERR_ASSEMBLY_NOT_RECORDED,
    ERR_WARRANTY_NOT_ELIGIBLE,
    invalid_state,
    not_found,
    raise_err,
    validation,
)
from middleware import (
    as_bool,
    as_date,
    as_enum,
    as_int,
    as_string,
    authenticate,
    get_json_body,
    require_customer_ownership,
    require_roles,
)
from response import success_list, success_object
from routes.customers import parse_pagination
from services.core import (
    approved_quote_for_ro,
    cancel_repair_order,
    check_asset_window_overlap,
    evaluate_warranty,
    recompute_pool_available_count,
    recompute_window,
)

bp = Blueprint("repair_orders", __name__)

FAILURE_MODES = [
    "SEAL_LEAK",
    "BEARING_FAILURE",
    "CAVITATION",
    "SEAT_LEAKAGE",
    "SPRING_DRIFT",
    "OTHER",
]
INTAKE_PRIORITIES = ["STANDARD", "SURGE"]

RO_TERMINAL = {"CLOSED", "CANCELLED"}


def get_ro_or_404(ro_id: str) -> dict:
    ro = DB.repair_orders.get(ro_id)
    if ro is None:
        not_found("Repair order not found")
    return ro


@bp.route("/repair-orders", methods=["POST"])
def create_repair_order():
    caller = authenticate()
    body = get_json_body()
    require_roles(caller, ["IntakeCoordinator", "Customer"])
    customer_id = as_string(body, "customer_id")
    asset_id = as_string(body, "asset_id")
    failure_mode = as_enum(body, "failure_mode", FAILURE_MODES)
    failure_description = as_string(body, "failure_description")
    intake_priority = as_enum(body, "intake_priority", INTAKE_PRIORITIES)
    planned_start_date = as_date(body, "planned_start_date")
    planned_end_date = as_date(body, "planned_end_date")
    estimated_bay_hours = as_int(body, "estimated_bay_hours")
    warranty_parent_ro_id = body.get("warranty_parent_ro_id")
    if warranty_parent_ro_id is not None and not isinstance(warranty_parent_ro_id, str):
        validation("warranty_parent_ro_id must be a string")
    exchange_requested = as_bool(body, "exchange_requested", default=False)

    if estimated_bay_hours is None or estimated_bay_hours <= 0:
        validation("estimated_bay_hours must be a positive integer")
    if planned_end_date < planned_start_date:
        validation("planned_end_date must be on or after planned_start_date")

    # Authorization: Customer may intake only its own orders.
    if caller.is_customer():
        require_customer_ownership(caller, customer_id)

    # Existence (left to right: customer, then asset, then warranty parent).
    customer = DB.customers.get(customer_id)
    if customer is None:
        not_found("Customer not found")
    asset = DB.assets.get(asset_id)
    if asset is None:
        not_found("Asset not found")
    if warranty_parent_ro_id is not None and warranty_parent_ro_id not in DB.repair_orders:
        not_found("Warranty parent repair order not found")

    # Temporal: asset closed-interval service overlap.
    check_asset_window_overlap(asset_id, planned_start_date, planned_end_date)

    # Referential: warranty eligibility.
    warranty_case = False
    repeat_failure_flag = False
    if warranty_parent_ro_id is not None:
        eligible, parent = evaluate_warranty(warranty_parent_ro_id, asset_id, customer_id)
        if not eligible:
            raise_err(
                ERR_WARRANTY_NOT_ELIGIBLE,
                "Warranty parent is not eligible (not CLOSED / wrong asset / wrong customer / outside warranty terms)",
            )
        warranty_case = True
        repeat_failure_flag = parent["failure_mode"] == failure_mode

    ro = stamp_new(
        {
            "customer_id": customer_id,
            "asset_id": asset_id,
            "warranty_parent_ro_id": warranty_parent_ro_id,
            "failure_mode": failure_mode,
            "failure_description": failure_description,
            "intake_priority": intake_priority,
            "planned_start_date": planned_start_date,
            "planned_end_date": planned_end_date,
            "estimated_bay_hours": estimated_bay_hours,
            "exchange_requested": exchange_requested,
            "status": "RECEIVED",
            "warranty_case": warranty_case,
            "repeat_failure_flag": repeat_failure_flag,
            "repair_round": 0,
            "repair_outcome": "NONE",
            "requires_certification": asset["equipment_class"] == "SAFETY_RELIEF_VALVE",
            "assembled_by_id": None,
            "capacity_window_id": None,
            "quote_attention_required": False,
            "invoiced_total_cents": None,
            "closed_at": None,
        }
    )
    DB.repair_orders[ro["id"]] = ro
    return success_object(ro, status=201)


@bp.route("/repair-orders", methods=["GET"])
def list_repair_orders():
    authenticate()
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    asset_id = request.args.get("asset_id")
    status = request.args.get("status")
    capacity_window_id = request.args.get("capacity_window_id")
    warranty_parent_ro_id = request.args.get("warranty_parent_ro_id")
    items = sorted(DB.repair_orders.values(), key=lambda r: (r["created_at"], r["id"]))
    if customer_id is not None:
        items = [r for r in items if r["customer_id"] == customer_id]
    if asset_id is not None:
        items = [r for r in items if r["asset_id"] == asset_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if capacity_window_id is not None:
        items = [r for r in items if r.get("capacity_window_id") == capacity_window_id]
    if warranty_parent_ro_id is not None:
        items = [r for r in items if r.get("warranty_parent_ro_id") == warranty_parent_ro_id]
    total = len(items)
    page = items[offset : offset + limit]
    return success_list(page, limit, offset, total)


@bp.route("/repair-orders/<rid>", methods=["GET"])
def get_repair_order(rid):
    caller = authenticate()
    ro = get_ro_or_404(rid)
    require_customer_ownership(caller, ro["customer_id"])
    return success_object(ro)


@bp.route("/repair-orders/<rid>/start-teardown", methods=["POST"])
def start_teardown(rid):
    caller = authenticate()
    get_json_body()
    require_roles(caller, ["IntakeCoordinator"])
    ro = get_ro_or_404(rid)
    if ro["status"] != "RECEIVED":
        invalid_state("Repair order is not in RECEIVED")
    ro["status"] = "IN_INSPECTION"
    touch(ro)
    return success_object(ro)


@bp.route("/repair-orders/<rid>/start-repair", methods=["POST"])
def start_repair(rid):
    caller = authenticate()
    get_json_body()
    require_roles(caller, ["Technician"])
    ro = get_ro_or_404(rid)
    if ro["status"] != "AUTHORIZED":
        invalid_state("Repair order is not in AUTHORIZED")
    if approved_quote_for_ro(ro["id"]) is None:
        invalid_state("No APPROVED quote exists for this repair order")
    ro["status"] = "IN_REPAIR"
    touch(ro)
    return success_object(ro)


@bp.route("/repair-orders/<rid>/log-assembly", methods=["POST"])
def log_assembly(rid):
    caller = authenticate()
    get_json_body()
    require_roles(caller, ["Technician"])
    ro = get_ro_or_404(rid)
    if ro["status"] != "IN_REPAIR":
        invalid_state("Repair order is not in IN_REPAIR")
    ro["assembled_by_id"] = caller.user_id
    touch(ro)
    return success_object(ro)


@bp.route("/repair-orders/<rid>/submit-for-test", methods=["POST"])
def submit_for_test(rid):
    caller = authenticate()
    get_json_body()
    require_roles(caller, ["Technician"])
    ro = get_ro_or_404(rid)
    if ro["status"] != "IN_REPAIR":
        invalid_state("Repair order is not in IN_REPAIR")
    if ro["requires_certification"] and not ro.get("assembled_by_id"):
        raise_err(
            ERR_ASSEMBLY_NOT_RECORDED,
            "Assembly must be logged before submitting a safety-relief valve for test",
        )
    ro["status"] = "IN_TEST"
    touch(ro)
    return success_object(ro)


@bp.route("/repair-orders/<rid>/close", methods=["POST"])
def close_repair_order(rid):
    caller = authenticate()
    get_json_body()
    require_roles(caller, ["IntakeCoordinator"])
    ro = get_ro_or_404(rid)
    if ro["status"] != "COMPLETE":
        invalid_state("Repair order is not in COMPLETE")

    from db import CLOCK

    ro["closed_at"] = CLOCK.now_str()
    approved = approved_quote_for_ro(ro["id"])
    ro["invoiced_total_cents"] = approved["total_cents"] if approved else None
    ro["repair_outcome"] = "FIRST_TIME_FIX" if ro["repair_round"] == 0 else "RE_REPAIR"

    # Release window hours.
    if ro.get("capacity_window_id"):
        window = DB.capacity_windows.get(ro["capacity_window_id"])
        if window is not None:
            window["bay_hours_reserved"] = max(
                0, window["bay_hours_reserved"] - ro["estimated_bay_hours"]
            )
            recompute_window(window)

    # Settle pool exchange: reserved unit -> ISSUED, replenish pool.
    for unit in list(DB.pool_units.values()):
        if unit["pool_status"] == "RESERVED" and unit.get("reserved_for_ro_id") == ro["id"]:
            unit["pool_status"] = "ISSUED"
            unit["reserved_for_ro_id"] = None
            touch(unit)
            recompute_pool_available_count(unit["customer_id"])
            replenishment = stamp_new(
                {
                    "customer_id": ro["customer_id"],
                    "asset_id": ro["asset_id"],
                    "pool_status": "IN_POOL",
                    "reserved_for_ro_id": None,
                }
            )
            DB.pool_units[replenishment["id"]] = replenishment
            recompute_pool_available_count(ro["customer_id"])

    ro["status"] = "CLOSED"
    touch(ro)
    return success_object(ro)


@bp.route("/repair-orders/<rid>/cancel", methods=["POST"])
def cancel_ro(rid):
    caller = authenticate()
    get_json_body()
    require_roles(caller, ["IntakeCoordinator", "Customer"])
    ro = get_ro_or_404(rid)
    if ro["status"] in RO_TERMINAL:
        invalid_state("Repair order is already in a terminal state")
    if caller.is_customer():
        require_customer_ownership(caller, ro["customer_id"])
        if ro["status"] not in ("RECEIVED", "IN_INSPECTION", "QUOTE_IN_PROGRESS"):
            invalid_state(
                "Customer may cancel only while the order is RECEIVED, IN_INSPECTION, or QUOTE_IN_PROGRESS"
            )
    cancel_repair_order(ro)
    return success_object(ro)
