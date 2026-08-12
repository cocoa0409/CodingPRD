"""Routes: material lots, material allocations, cut plans."""
from flask import Blueprint, g, request

from mill.common import (
    ALL_ROLES,
    ApiError,
    D,
    endpoint,
    get_body,
    list_response,
    new_rec,
    now_iso,
    ok,
    pub,
    q3,
    r2,
    r3,
    req_field,
    req_num,
    req_pos_num,
    touch,
)
from mill.logic import (
    allocs_of_line,
    allocs_of_lot,
    eval_line,
    final_yards,
    lines_of,
    plans_of_line,
    recompute_lot,
    recompute_order_credit,
    release_allocation,
)
from mill.store import store

bp = Blueprint("materials", __name__)

WRITE_RECEIVER = ["MaterialReceiver"]
WRITE_QI = ["QualityInspector"]
WRITE_PLANNER = ["ProductionPlanner"]


def _find_lot(lid):
    rec = store.material_lots.get(lid)
    if not rec:
        raise ApiError("ERR_MATERIAL_LOT_NOT_FOUND", 404, "MaterialLot not found")
    return rec


def _find_alloc(aid):
    rec = store.allocations.get(aid)
    if not rec:
        raise ApiError("ERR_ALLOCATION_NOT_FOUND", 404, "MaterialAllocation not found")
    return rec


def _find_plan(pid):
    rec = store.cut_plans.get(pid)
    if not rec:
        raise ApiError("ERR_CUT_PLAN_NOT_FOUND", 404, "CutPlan not found")
    return rec


def _find_line(lid):
    rec = store.order_lines.get(lid)
    if not rec:
        raise ApiError("ERR_ORDER_LINE_NOT_FOUND", 404, "OrderLine not found")
    return rec


# ---------------------------------------------------------------------------
# MaterialLot
# ---------------------------------------------------------------------------


@bp.post("/mill/material-lots")
@endpoint(WRITE_RECEIVER)
def create_lot():
    b = get_body()
    fabric_spec_id = req_field(b, "fabric_spec_id")
    expected_yards = req_pos_num(b, "expected_yards")
    order_line_id = b.get("order_line_id")
    spec = store.fabric_specs.get(fabric_spec_id)
    if not spec:
        raise ApiError("ERR_FABRIC_SPEC_NOT_FOUND", 404, "FabricSpec not found")
    line = None
    if order_line_id is not None:
        line = store.order_lines.get(order_line_id)
        if not line:
            raise ApiError("ERR_ORDER_LINE_NOT_FOUND", 404, "OrderLine not found")
    if spec["origin"] == "CUSTOMER" and order_line_id is None:
        raise ApiError(
            "ERR_LOT_BINDING_INVALID", 422, "A COM lot must name its bound order_line_id"
        )
    if spec["origin"] == "PLANT" and order_line_id is not None:
        raise ApiError(
            "ERR_LOT_BINDING_INVALID", 422, "A plant lot must not name an order_line_id"
        )
    rec = new_rec()
    rec.update(
        {
            "fabric_spec_id": fabric_spec_id,
            "order_line_id": order_line_id,
            "parent_lot_id": None,
            "ownership": spec["origin"],
            "expected_yards": expected_yards,
            "received_yards": None,
            "measured_width_inches": None,
            "usable_yards": None,
            "rejected_yards": None,
            "allocated_yards": 0,
            "available_yards": 0,
            "status": "EXPECTED",
            "received_at": None,
            "inspected_by": None,
        }
    )
    store.material_lots[rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.get("/mill/material-lots")
@endpoint(ALL_ROLES)
def list_lots():
    recs = list(store.material_lots.values())
    for param in ("fabric_spec_id", "order_line_id", "parent_lot_id", "status"):
        v = request.args.get(param)
        if v:
            recs = [l for l in recs if l[param] == v]
    return list_response(recs)


@bp.get("/mill/material-lots/<lid>")
@endpoint(ALL_ROLES)
def get_lot(lid):
    return ok(pub(_find_lot(lid)))


@bp.post("/mill/material-lots/<lid>/receive")
@endpoint(WRITE_RECEIVER)
def receive_lot(lid):
    b = get_body()
    received_yards = req_num(b, "received_yards")
    lot = _find_lot(lid)
    if lot["status"] != "EXPECTED":
        raise ApiError("ERR_LOT_INVALID_STATE", 409, "Lot is not in EXPECTED")
    if D(received_yards) <= 0 or D(received_yards) > D(lot["expected_yards"]) * D("1.10"):
        raise ApiError(
            "ERR_OVER_RECEIPT",
            422,
            "received_yards must be > 0 and no more than expected_yards plus 10%",
        )
    lot["received_yards"] = r3(received_yards)
    lot["received_at"] = now_iso()
    lot["status"] = "RECEIVED"
    touch(lot)
    return ok(pub(lot))


@bp.post("/mill/material-lots/<lid>/inspect")
@endpoint(WRITE_QI)
def inspect_lot(lid):
    b = get_body()
    result = req_field(b, "result")
    if result not in ("PASS", "FAIL"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "result must be PASS or FAIL")
    usable_yards = None
    rejected_yards = None
    measured_width = None
    if result == "PASS":
        usable_yards = req_num(b, "usable_yards")
        rejected_yards = req_num(b, "rejected_yards")
        if D(usable_yards) < 0 or D(rejected_yards) < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "yardage fields must be >= 0")
        measured_width = req_num(b, "measured_width_inches")
        if D(measured_width) <= 0:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "measured_width_inches must be positive"
            )
    lot = _find_lot(lid)
    if lot["status"] != "RECEIVED":
        raise ApiError("ERR_LOT_INVALID_STATE", 409, "Lot is not in RECEIVED")
    lot["inspected_by"] = g.user_id
    if result == "PASS":
        if D(usable_yards) <= 0:
            raise ApiError(
                "ERR_INSPECTION_YARDAGE_MISMATCH", 422, "usable_yards must be > 0 on PASS"
            )
        if q3(D(usable_yards) + D(rejected_yards)) != q3(D(lot["received_yards"])):
            raise ApiError(
                "ERR_INSPECTION_YARDAGE_MISMATCH",
                422,
                "usable_yards + rejected_yards must equal received_yards",
            )
        lot["usable_yards"] = r3(usable_yards)
        lot["rejected_yards"] = r3(rejected_yards)
        lot["measured_width_inches"] = measured_width
        lot["status"] = "AVAILABLE"
        touch(lot)
        recompute_lot(lot)
        # COM auto-allocation to the bound line.
        if lot["ownership"] == "CUSTOMER" and lot["order_line_id"]:
            line = store.order_lines.get(lot["order_line_id"])
            if line and line["status"] in ("MATERIAL_SHORTFALL", "ALLOCATED"):
                eval_line(line)
                amount = min(D(lot["usable_yards"]), D(line["shortfall_yards"]))
                if amount > 0:
                    alloc = new_rec()
                    alloc.update(
                        {
                            "lot_id": lot["id"],
                            "order_line_id": line["id"],
                            "yards": r3(amount),
                            "consumed_yards": 0,
                            "status": "ACTIVE",
                        }
                    )
                    store.allocations[alloc["id"]] = alloc
                    recompute_lot(lot)
                    eval_line(line)
                    order = store.orders.get(line["order_id"])
                    if order:
                        recompute_order_credit(order)
    else:
        lot["usable_yards"] = 0
        lot["rejected_yards"] = lot["received_yards"]
        lot["status"] = "REJECTED"
        touch(lot)
    return ok(pub(lot))


@bp.post("/mill/material-lots/<lid>/reject-lot")
@endpoint(WRITE_QI)
def reject_lot(lid):
    lot = _find_lot(lid)
    if lot["status"] != "AVAILABLE":
        raise ApiError("ERR_LOT_NOT_AVAILABLE", 409, "Lot is not AVAILABLE")
    affected_lines = {a["order_line_id"] for a in allocs_of_lot(lid) if a["status"] == "ACTIVE"}
    for a in allocs_of_lot(lid):
        if a["status"] == "ACTIVE":
            a["status"] = "RELEASED"
            touch(a)
    lot["status"] = "REJECTED"
    touch(lot)
    recompute_lot(lot)
    seen_orders = set()
    for line_id in affected_lines:
        line = store.order_lines.get(line_id)
        if line:
            eval_line(line)
            if line["order_id"] not in seen_orders:
                seen_orders.add(line["order_id"])
                order = store.orders.get(line["order_id"])
                if order:
                    recompute_order_credit(order)
    return ok(pub(lot))


@bp.post("/mill/material-lots/<lid>/return-to-customer")
@endpoint(WRITE_RECEIVER)
def return_lot(lid):
    lot = _find_lot(lid)
    if lot["status"] != "REJECTED":
        raise ApiError("ERR_LOT_INVALID_STATE", 409, "Lot is not in REJECTED")
    if lot["ownership"] != "CUSTOMER":
        raise ApiError("ERR_LOT_NOT_RETURNABLE", 409, "Only CUSTOMER-owned lots can be returned")
    lot["status"] = "RETURNED"
    touch(lot)
    return ok(pub(lot))


@bp.post("/mill/material-lots/<lid>/split")
@endpoint(WRITE_RECEIVER)
def split_lot(lid):
    b = get_body()
    yards_to_move = req_pos_num(b, "yards_to_move")
    lot = _find_lot(lid)
    if lot["status"] != "AVAILABLE":
        raise ApiError("ERR_LOT_NOT_AVAILABLE", 409, "Lot is not AVAILABLE")
    if D(yards_to_move) > D(lot["available_yards"]):
        raise ApiError(
            "ERR_INSUFFICIENT_YARDAGE", 422, "yards_to_move exceeds the lot's available_yards"
        )
    child = new_rec()
    child.update(
        {
            "fabric_spec_id": lot["fabric_spec_id"],
            "order_line_id": lot["order_line_id"],
            "parent_lot_id": lot["id"],
            "ownership": lot["ownership"],
            "expected_yards": r3(yards_to_move),
            "received_yards": r3(yards_to_move),
            "measured_width_inches": lot["measured_width_inches"],
            "usable_yards": r3(yards_to_move),
            "rejected_yards": 0,
            "allocated_yards": 0,
            "available_yards": r3(yards_to_move),
            "status": "AVAILABLE",
            "received_at": lot["received_at"],
            "inspected_by": lot["inspected_by"],
        }
    )
    store.material_lots[child["id"]] = child
    lot["usable_yards"] = r3(D(lot["usable_yards"]) - D(yards_to_move))
    touch(lot)
    recompute_lot(lot)
    return ok(pub(child), 201)


# ---------------------------------------------------------------------------
# MaterialAllocation
# ---------------------------------------------------------------------------


@bp.post("/mill/material-allocations")
@endpoint(WRITE_PLANNER)
def create_allocation():
    b = get_body()
    lot_id = req_field(b, "lot_id")
    order_line_id = req_field(b, "order_line_id")
    yards = req_pos_num(b, "yards")
    lot = store.material_lots.get(lot_id)
    if not lot:
        raise ApiError("ERR_MATERIAL_LOT_NOT_FOUND", 404, "MaterialLot not found")
    line = store.order_lines.get(order_line_id)
    if not line:
        raise ApiError("ERR_ORDER_LINE_NOT_FOUND", 404, "OrderLine not found")
    if lot["status"] != "AVAILABLE":
        raise ApiError("ERR_LOT_NOT_AVAILABLE", 409, "Lot is not AVAILABLE")
    if line["status"] not in ("MATERIAL_SHORTFALL", "ALLOCATED"):
        raise ApiError(
            "ERR_LINE_STAGE_MISMATCH",
            409,
            "Line must be in MATERIAL_SHORTFALL or ALLOCATED to accept an allocation",
        )
    # Binding: COM lots only to their bound line; PLANT lots only to PLANT_STOCK
    # lines of the same fabric spec.
    if lot["ownership"] == "CUSTOMER":
        if lot["order_line_id"] != line["id"]:
            raise ApiError(
                "ERR_LOT_BINDING_INVALID", 422, "A COM lot may only allocate to its bound line"
            )
    else:
        if line["fabric_source"] != "PLANT_STOCK" or line["fabric_spec_id"] != lot["fabric_spec_id"]:
            raise ApiError(
                "ERR_LOT_BINDING_INVALID",
                422,
                "A plant lot may only allocate to PLANT_STOCK lines of the same fabric spec",
            )
    if D(yards) > D(lot["available_yards"]):
        raise ApiError(
            "ERR_INSUFFICIENT_YARDAGE", 422, "yards exceeds the lot's available_yards"
        )
    rec = new_rec()
    rec.update(
        {
            "lot_id": lot_id,
            "order_line_id": order_line_id,
            "yards": r3(yards),
            "consumed_yards": 0,
            "status": "ACTIVE",
        }
    )
    store.allocations[rec["id"]] = rec
    recompute_lot(lot)
    eval_line(line)
    order = store.orders.get(line["order_id"])
    if order:
        recompute_order_credit(order)
    return ok(pub(rec), 201)


@bp.get("/mill/material-allocations")
@endpoint(ALL_ROLES)
def list_allocations():
    recs = list(store.allocations.values())
    for param in ("lot_id", "order_line_id", "status"):
        v = request.args.get(param)
        if v:
            recs = [a for a in recs if a[param] == v]
    return list_response(recs)


@bp.get("/mill/material-allocations/<aid>")
@endpoint(ALL_ROLES)
def get_allocation(aid):
    return ok(pub(_find_alloc(aid)))


@bp.post("/mill/material-allocations/<aid>/release")
@endpoint(WRITE_PLANNER)
def release_allocation_endpoint(aid):
    alloc = _find_alloc(aid)
    if alloc["status"] != "ACTIVE":
        raise ApiError("ERR_ALLOCATION_INVALID_STATE", 409, "Allocation is not ACTIVE")
    release_allocation(alloc)
    return ok(pub(alloc))


# ---------------------------------------------------------------------------
# CutPlan
# ---------------------------------------------------------------------------


@bp.post("/mill/order-lines/<line_id>/cut-plans")
@endpoint(WRITE_PLANNER)
def create_cut_plan(line_id):
    b = get_body()
    if b.get("expected_order_line_version") is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "expected_order_line_version is required"
        )
    expected = b["expected_order_line_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "expected_order_line_version must be an integer"
        )
    line = _find_line(line_id)
    if line["version"] != expected:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_order_line_version does not match the line's current version",
        )
    # Supersede the line's existing DRAFT/APPROVED plan.
    for plan in plans_of_line(line_id):
        if plan["status"] in ("DRAFT", "APPROVED"):
            was_approved = plan["status"] == "APPROVED"
            plan["status"] = "SUPERSEDED"
            touch(plan)
            if was_approved:
                line["required_yards_final"] = None
                eval_line(line)
    rec = new_rec()
    rec.update(
        {
            "order_line_id": line_id,
            "marker_length_yards": None,
            "required_yards_final": None,
            "utilization_pct": None,
            "waste_yards": None,
            "status": "DRAFT",
        }
    )
    store.cut_plans[rec["id"]] = rec
    touch(line)  # the create itself increments the line's version by one
    return ok(pub(rec), 201)


@bp.get("/mill/cut-plans")
@endpoint(ALL_ROLES)
def list_cut_plans():
    recs = list(store.cut_plans.values())
    v = request.args.get("order_line_id")
    if v:
        recs = [p for p in recs if p["order_line_id"] == v]
    return list_response(recs)


@bp.get("/mill/cut-plans/<pid>")
@endpoint(ALL_ROLES)
def get_cut_plan(pid):
    return ok(pub(_find_plan(pid)))


@bp.post("/mill/cut-plans/<pid>/approve")
@endpoint(WRITE_PLANNER)
def approve_cut_plan(pid):
    b = get_body()
    marker_length_yards = req_pos_num(b, "marker_length_yards")
    plan = _find_plan(pid)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_CUT_PLAN_NOT_DRAFT", 409, "Cut plan is not in DRAFT")
    line = _find_line(plan["order_line_id"])
    if line["status"] != "ALLOCATED":
        raise ApiError("ERR_LINE_STAGE_MISMATCH", 409, "Line is not ALLOCATED")
    measured = None
    for a in allocs_of_line(line["id"]):
        if a["status"] != "ACTIVE":
            continue
        lot = store.material_lots.get(a["lot_id"])
        if lot and lot["measured_width_inches"] is not None:
            w = D(lot["measured_width_inches"])
            measured = w if measured is None else min(measured, w)
    if measured is None:
        raise ApiError(
            "ERR_INSUFFICIENT_ALLOCATION",
            422,
            "Line has no allocated lots with a measured width",
        )
    final = final_yards(marker_length_yards, measured)
    if D(line["allocated_yards"]) < D(final):
        raise ApiError(
            "ERR_INSUFFICIENT_ALLOCATION",
            422,
            "allocated_yards is below the computed required_yards_final",
        )
    plan["marker_length_yards"] = marker_length_yards
    plan["required_yards_final"] = final
    plan["status"] = "APPROVED"
    touch(plan)
    line["required_yards_final"] = final
    eval_line(line)
    return ok(pub(plan))


@bp.post("/mill/cut-plans/<pid>/revise")
@endpoint(WRITE_PLANNER)
def revise_cut_plan(pid):
    plan = _find_plan(pid)
    if plan["status"] != "APPROVED":
        raise ApiError("ERR_CUT_PLAN_NOT_APPROVED", 409, "Cut plan is not APPROVED")
    plan["status"] = "DRAFT"
    touch(plan)
    line = store.order_lines.get(plan["order_line_id"])
    if line:
        line["required_yards_final"] = None
        eval_line(line)
    return ok(pub(plan))


@bp.post("/mill/cut-plans/<pid>/record-cut")
@endpoint(WRITE_PLANNER)
def record_cut(pid):
    plan = _find_plan(pid)
    if plan["status"] != "APPROVED":
        raise ApiError("ERR_CUT_PLAN_NOT_APPROVED", 409, "Cut plan is not APPROVED")
    line = _find_line(plan["order_line_id"])
    has_completed_cut = any(
        b["operation"] == "CUT" and b["status"] == "COMPLETED"
        for b in store.cell_bookings.values()
        if b["order_line_id"] == line["id"]
    )
    if not has_completed_cut:
        raise ApiError(
            "ERR_LINE_STAGE_MISMATCH",
            409,
            "record-cut requires a COMPLETED CUT cell booking on the line",
        )
    # Consume ALL of the line's ACTIVE allocations whole, created_at ASC.
    total_consumed = D("0")
    affected_lots = []
    for a in allocs_of_line(line["id"]):
        if a["status"] == "ACTIVE":
            a["status"] = "CONSUMED"
            a["consumed_yards"] = a["yards"]
            total_consumed += D(a["yards"])
            touch(a)
            lot = store.material_lots.get(a["lot_id"])
            if lot and lot["id"] not in [l["id"] for l in affected_lots]:
                affected_lots.append(lot)
    for lot in affected_lots:
        recompute_lot(lot)
    final = D(line["required_yards_final"])
    plan["utilization_pct"] = r2(final / total_consumed * D("100"))
    plan["waste_yards"] = r3(total_consumed - final)
    plan["status"] = "CUT"
    touch(plan)
    for lot in affected_lots:
        has_active = any(
            a["status"] == "ACTIVE" for a in allocs_of_lot(lot["id"])
        )
        if not has_active and D(lot["available_yards"]) <= 0 and lot["status"] == "AVAILABLE":
            lot["status"] = "DEPLETED"
            touch(lot)
    line["status"] = "CUT"
    line["allocated_yards"] = 0
    line["shortfall_yards"] = r3(final)
    touch(line)
    order = store.orders.get(line["order_id"])
    if order:
        recompute_order_credit(order)
    return ok(pub(plan))
