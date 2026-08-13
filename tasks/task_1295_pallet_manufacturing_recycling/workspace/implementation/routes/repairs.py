"""RepairWorkOrder endpoints. Completion forks: outcome A/B creates a recycled
InventoryLot; FAILED cycles the core back to UNSORTED/YARD in place."""

from flask import Blueprint, request

from db import db
from errors import raise_err
from middleware import (
    require_roles, get_json_body, parse_pagination, paginate,
    req_field, opt_field, as_str, as_int, as_enum,
)
from response import success
from services.calc import recycled_repair_unit_cost_cents
from services.helpers import (
    init_common, touch, serialize, serialize_list, sorted_by_creation,
    get_or_404, ref_or_404,
)

bp = Blueprint("repairs", __name__)

TARGET_GRADES = ("A", "B")
OUTCOME_GRADES = ("A", "B", "FAILED")


def create_recycled_lot(core, work_order, outcome_grade):
    """Build the RECYCLED_REPAIR InventoryLot for a successful repair."""
    spec = db.specs.get(work_order["target_spec_id"])
    batch = db.core_batches.get(core["batch_id"])
    if batch is not None:
        unit_cost = recycled_repair_unit_cost_cents(
            batch, outcome_grade,
            work_order["parts_cost_cents"], work_order["actual_labor_minutes"],
        )
    else:
        # Pool-returned cores have no owning batch: parts + labor only.
        unit_cost = (
            work_order["parts_cost_cents"]
            + 95 * work_order["actual_labor_minutes"]
        )
    requires_ht = spec["requires_heat_treatment_default"] if spec is not None else False
    lot = {
        "spec_id": work_order["target_spec_id"],
        "origin_type": "RECYCLED_REPAIR",
        "quantity_total": 1,
        "quantity_available": 1,
        "quality_grade": outcome_grade,
        "heat_treat_status": "PENDING_HT" if requires_ht else "NOT_REQUIRED",
        "ispm15_mark_id": None,
        "unit_cost_cents": unit_cost,
        "status": "AVAILABLE",
    }
    init_common(lot)
    db.inventory_lots[lot["id"]] = lot
    return lot


@bp.post("/pallet-ops/repair-orders")
def create_repair_order():
    require_roles("YardSupervisor")
    body = get_json_body()
    core_unit_id = as_str(req_field(body, "core_unit_id"), "core_unit_id")
    core = ref_or_404(db.core_units, core_unit_id, "core_unit_id")
    target_spec_id = as_str(req_field(body, "target_spec_id"), "target_spec_id")
    ref_or_404(db.specs, target_spec_id, "target_spec_id")
    target_grade = as_enum(req_field(body, "target_grade"), "target_grade", TARGET_GRADES)
    labor_est = as_int(req_field(body, "labor_minutes_estimate"), "labor_minutes_estimate", minimum=1)
    parts_cost = opt_field(body, "parts_cost_cents", 0)
    parts_cost = as_int(parts_cost, "parts_cost_cents", minimum=0)

    # Repair eligibility gates (priority order per scaffold state machine):
    # grade first, then yard presence, then no open work order.
    if core["grade"] not in ("A", "B"):
        raise_err("ERR_CORE_NOT_REPAIRABLE", "Repair open requires core grade IN {A,B}")
    if core["processing_status"] != "YARD":
        raise_err("ERR_CORE_NOT_IN_YARD", "Repair open requires processing_status == YARD")
    if any(
        wo["core_unit_id"] == core_unit_id and wo["status"] in ("OPEN", "IN_PROGRESS")
        for wo in db.repair_orders.values()
    ):
        raise_err(
            "ERR_REPAIR_ALREADY_OPEN",
            "An OPEN/IN_PROGRESS work order already exists for this core",
        )

    wo = {
        "core_unit_id": core_unit_id,
        "target_spec_id": target_spec_id,
        "target_grade": target_grade,
        "labor_minutes_estimate": labor_est,
        "parts_cost_cents": parts_cost,
        "actual_labor_minutes": None,
        "outcome_grade": None,
        "status": "OPEN",
    }
    init_common(wo)
    db.repair_orders[wo["id"]] = wo

    core["processing_status"] = "IN_REPAIR"
    touch(core)
    return success(serialize(wo), status=201)


@bp.get("/pallet-ops/repair-orders")
def list_repair_orders():
    require_roles()
    limit, offset = parse_pagination()
    items = list(db.repair_orders.values())
    core_unit_id = request.args.get("core_unit_id")
    if core_unit_id is not None:
        items = [w for w in items if w["core_unit_id"] == core_unit_id]
    status = request.args.get("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    target_spec_id = request.args.get("target_spec_id")
    if target_spec_id is not None:
        items = [w for w in items if w["target_spec_id"] == target_spec_id]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success(serialize_list(page), pagination=pagination, is_list=True)


@bp.get("/pallet-ops/repair-orders/<wid>")
def get_repair_order(wid):
    require_roles()
    wo = get_or_404(db.repair_orders, wid, "RepairWorkOrder")
    return success(serialize(wo))


@bp.post("/pallet-ops/repair-orders/<wid>/start")
def start_repair_order(wid):
    require_roles("YardSupervisor")
    wo = get_or_404(db.repair_orders, wid, "RepairWorkOrder")
    if wo["status"] != "OPEN":
        raise_err("ERR_WO_NOT_OPEN", "start requires work order OPEN")
    wo["status"] = "IN_PROGRESS"
    touch(wo)
    return success(serialize(wo))


@bp.post("/pallet-ops/repair-orders/<wid>/complete")
def complete_repair_order(wid):
    require_roles("YardSupervisor")
    wo = get_or_404(db.repair_orders, wid, "RepairWorkOrder")
    body = get_json_body()
    outcome = as_enum(req_field(body, "outcome_grade"), "outcome_grade", OUTCOME_GRADES)
    actual_labor = as_int(req_field(body, "actual_labor_minutes"), "actual_labor_minutes", minimum=0)

    if wo["status"] != "IN_PROGRESS":
        raise_err("ERR_WO_NOT_IN_PROGRESS", "complete requires work order IN_PROGRESS")

    wo["outcome_grade"] = outcome
    wo["actual_labor_minutes"] = actual_labor
    wo["status"] = "COMPLETED"
    touch(wo)

    core = db.core_units.get(wo["core_unit_id"])
    if core is not None:
        core["repair_cycle_count"] += 1
        if outcome in ("A", "B"):
            core["processing_status"] = "REPAIRED"
            create_recycled_lot(core, wo, outcome)
        else:
            # FAILED: cycle in place -- same row, grade back to UNSORTED.
            core["grade"] = "UNSORTED"
            core["processing_status"] = "YARD"
        touch(core)
    return success(serialize(wo))


@bp.post("/pallet-ops/repair-orders/<wid>/abort")
def abort_repair_order(wid):
    require_roles("YardSupervisor")
    wo = get_or_404(db.repair_orders, wid, "RepairWorkOrder")
    if wo["status"] != "OPEN":
        raise_err("ERR_WO_NOT_OPEN", "abort requires work order OPEN")
    wo["status"] = "ABORTED"
    touch(wo)
    core = db.core_units.get(wo["core_unit_id"])
    if core is not None:
        core["processing_status"] = "YARD"
        touch(core)
    return success(serialize(wo))
