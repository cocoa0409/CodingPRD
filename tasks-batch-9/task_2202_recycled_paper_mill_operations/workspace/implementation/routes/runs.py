from decimal import Decimal

from flask import Blueprint

import auth
import calc
import common
import response
import shape
import store
from errors import err
from shape import D, q

bp = Blueprint("runs", __name__)
ZERO = Decimal("0")
QUALITY_GATE = Decimal("85.00")


def _need_machine_run(machine_id, run_id):
    machine = common.need("paper_machines", machine_id, "ERR_MACHINE_NOT_FOUND")
    run = store.get("production_runs", run_id)
    if run is None or run["machine_id"] != machine["id"]:
        raise err("ERR_RUN_NOT_FOUND", "production run not found on this machine")
    return machine, run


@bp.get("/production-runs/<rid>")
def get_run(rid):
    auth.require_roles("MillPlanner", "MachineOperator", "QualityLab", "Customer")
    return response.ok(common.view(common.need("production_runs", rid, "ERR_RUN_NOT_FOUND")))


@bp.get("/production-runs")
def list_runs():
    auth.require_roles("MillPlanner", "MachineOperator", "QualityLab")
    limit, offset = shape.pagination()
    rows = common.filtered("production_runs", {
        "machine_id": "machine_id",
        "pulp_batch_id": "pulp_batch_id",
        "product_code": "product_code",
        "run_status": "run_status",
        "quality_status": "quality_status",
    })
    return response.ok_list(common.views(shape.paginate(rows, limit, offset)), limit, offset, len(rows))


@bp.post("/paper-machines/<mid>/runs/<rid>/start")
def start_run(mid, rid):
    auth.require_roles("MachineOperator")
    machine, run = _need_machine_run(mid, rid)
    shape.reject_unexpected_version(shape.body())
    if run["run_status"] != "SCHEDULED":
        raise err("ERR_RUN_INVALID_STATE", "run is not SCHEDULED")
    if machine["status"] == "DOWN":
        raise err("ERR_RUN_INVALID_STATE", "machine is DOWN")
    for gc in store.all_rows("grade_changes"):
        if gc["to_run_id"] == run["id"] and gc["status"] != "EXECUTED":
            raise err("ERR_RUN_INVALID_STATE", "inbound grade change has not been executed")
    permit = common.the_permit()
    if permit is not None and permit["compliance_posture"] == "EXCEEDANCE":
        raise err("ERR_PERMIT_EXCEEDANCE_BLOCK", "effluent permit posture is EXCEEDANCE")
    spec = common.need_spec(run["product_code"])
    batch = store.get("pulp_batches", run["pulp_batch_id"])
    if spec["requires_deink_pulp"]:
        if batch is None or int(batch["deink_pass_count"]) < 1:
            raise err("ERR_DEINK_PULP_REQUIRED", "product requires deinked pulp")
    if batch is None or batch["status"] != "APPROVED" \
            or D(batch["available_tons"]) < D(run["pulp_draw_tons"]):
        raise err("ERR_INSUFFICIENT_PULP", "pulp batch is not APPROVED or has insufficient tonnage")
    run["run_status"] = "RUNNING"
    run["started_by_user_id"] = auth.user_id()
    store.touch("production_runs", run)
    common.recompute_batch_available(batch)
    store.touch("pulp_batches", batch)
    for o in store.all_rows("customer_orders"):
        if o.get("scheduled_run_id") == run["id"] and o["status"] == "SCHEDULED":
            o["status"] = "IN_PRODUCTION"
            store.touch("customer_orders", o)
    store.touch("paper_machines", machine)
    return response.ok(common.view(run))


def _validate_reels(data):
    entries = shape.get_list(data, "reel_readings", 1, 10)
    seen = set()
    prev = None
    out = []
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise err("ERR_VALIDATION", "reel_readings[%d] must be an object" % i)
        no = shape.get_int(e, "reel_no", minimum=1)
        if no in seen:
            raise err("ERR_VALIDATION", "reel_no must be unique")
        if prev is not None and no <= prev:
            raise err("ERR_VALIDATION", "reel_no must be ascending")
        seen.add(no)
        prev = no
        out.append({
            "reel_no": no,
            "reel_tons": shape.get_num(e, "reel_tons", exclusive_min=0, places=3),
            "basis_weight_gsm": shape.get_num(e, "basis_weight_gsm", minimum=0, places=1),
            "moisture_pct": shape.get_num(e, "moisture_pct", minimum=0, places=2),
            "sct_kn_m": shape.get_num(e, "sct_kn_m", minimum=0, places=2),
        })
    return out


@bp.post("/paper-machines/<mid>/runs/<rid>/complete")
def complete_run(mid, rid):
    auth.require_roles("MachineOperator")
    machine, run = _need_machine_run(mid, rid)
    data = shape.body()
    shape.reject_unexpected_version(data)
    reels = _validate_reels(data)
    broke = shape.get_num(data, "broke_tons", required=False, minimum=0, default=0, places=3)
    if run["run_status"] != "RUNNING":
        raise err("ERR_RUN_INVALID_STATE", "run is not RUNNING")
    spec = common.need_spec(run["product_code"])
    run["reel_readings"] = reels
    run["broke_tons"] = broke
    run["off_spec_reel_count"] = calc.off_spec_reel_count(reels, spec)
    run["provisional_quality_index"] = calc.run_quality_index_provisional(reels, spec)
    run["run_status"] = "COMPLETED"
    run["quality_status"] = "PROVISIONAL"
    common.recompute_run_produced(run)
    store.touch("production_runs", run)
    if D(broke) != ZERO:
        common.append_reject("MACHINE_BROKE", run["id"], broke)
    machine["current_product_code"] = run["product_code"]
    for gc in store.all_rows("grade_changes"):
        if gc["from_run_id"] == run["id"] and gc["status"] == "PLANNED":
            gc["status"] = "EXECUTED"
            store.touch("grade_changes", gc)
            common.append_reject("TRANSITION_WASTE", gc["id"], gc["transition_waste_tons"])
    store.touch("paper_machines", machine)
    return response.ok(common.view(run))


@bp.post("/paper-machines/<mid>/runs/<rid>/abort")
def abort_run(mid, rid):
    auth.require_roles("MillPlanner")
    machine, run = _need_machine_run(mid, rid)
    shape.reject_unexpected_version(shape.body())
    if run["run_status"] != "RUNNING":
        raise err("ERR_RUN_INVALID_STATE", "run is not RUNNING")
    run["run_status"] = "ABORTED"
    run["quality_status"] = "CONDEMNED"
    store.touch("production_runs", run)
    batch = store.get("pulp_batches", run["pulp_batch_id"])
    if batch is not None:
        common.recompute_batch_available(batch)
        store.touch("pulp_batches", batch)
    for rs in common.run_roll_sets(run["id"]):
        if rs["status"] in ("WOUND", "WRAPPED"):
            rs["status"] = "SCRAPPED"
            store.touch("roll_sets", rs)
            common.append_reject("MACHINE_BROKE", run["id"], rs["net_tons"])
    common.recompute_run_produced(run)
    common.deschedule_orders_of_run(run["id"])
    store.touch("paper_machines", machine)
    return response.ok(common.view(run))


@bp.post("/paper-machines/<mid>/runs/<rid>/certify")
def certify_run(mid, rid):
    auth.require_roles("QualityLab")
    machine, run = _need_machine_run(mid, rid)
    shape.reject_unexpected_version(shape.body())
    if run["quality_status"] != "PROVISIONAL":
        raise err("ERR_QUALITY_INVALID_STATE", "run quality axis is not PROVISIONAL")
    if auth.user_id() == run.get("started_by_user_id"):
        raise err("ERR_SOD_SAME_OPERATOR", "the operator who started the run may not certify it")
    spec = common.need_spec(run["product_code"])
    index = calc.run_quality_index_certified(run["reel_readings"], spec)
    if int(run["off_spec_reel_count"]) != 0:
        raise err("ERR_QUALITY_INVALID_STATE", "run has off-spec reels and must be held")
    if D(index) < QUALITY_GATE:
        raise err("ERR_QUALITY_INVALID_STATE", "certified quality index below 85.00")
    run["certified_quality_index"] = index
    run["certified_by_user_id"] = auth.user_id()
    run["quality_status"] = "CERTIFIED"
    store.touch("production_runs", run)
    _ = machine
    return response.ok(common.view(run))


@bp.post("/paper-machines/<mid>/runs/<rid>/hold")
def hold_run(mid, rid):
    auth.require_roles("QualityLab")
    machine, run = _need_machine_run(mid, rid)
    shape.reject_unexpected_version(shape.body())
    if run["quality_status"] != "PROVISIONAL":
        raise err("ERR_QUALITY_INVALID_STATE", "run quality axis is not PROVISIONAL")
    spec = common.need_spec(run["product_code"])
    index = calc.run_quality_index_certified(run["reel_readings"], spec)
    if int(run["off_spec_reel_count"]) == 0 and D(index) >= QUALITY_GATE:
        raise err("ERR_QUALITY_INVALID_STATE", "run has no off-spec reels and meets the quality gate")
    run["certified_quality_index"] = index
    run["quality_status"] = "HELD"
    store.touch("production_runs", run)
    affected = set()
    for rs in common.run_roll_sets(run["id"]):
        if rs["status"] in ("WOUND", "WRAPPED", "ALLOCATED"):
            if rs.get("allocated_order_id"):
                affected.add(rs["allocated_order_id"])
            rs["status"] = "QUARANTINED"
            rs["quarantine_reason"] = "RUN_HELD"
            rs["allocated_order_id"] = None
            store.touch("roll_sets", rs)
    common.recompute_run_produced(run)
    for oid in sorted(affected):
        order = store.get("customer_orders", oid)
        if order is not None:
            common.unwind_order_after_quarantine(order)
    _ = machine
    return response.ok(common.view(run))


@bp.post("/paper-machines/<mid>/runs/<rid>/rework")
def rework_run(mid, rid):
    auth.require_roles("MillPlanner")
    machine, run = _need_machine_run(mid, rid)
    shape.reject_unexpected_version(shape.body())
    if run["quality_status"] != "HELD":
        raise err("ERR_QUALITY_INVALID_STATE", "run quality axis is not HELD")
    run["quality_status"] = "REWORK"
    store.touch("production_runs", run)
    for rs in common.run_roll_sets(run["id"]):
        if rs["status"] == "QUARANTINED":
            rs["status"] = "REWOUND"
            rs["rewind_count"] = int(rs["rewind_count"]) + 1
            store.touch("roll_sets", rs)
    common.recompute_run_produced(run)
    _ = machine
    return response.ok(common.view(run))


@bp.post("/paper-machines/<mid>/runs/<rid>/resubmit-quality")
def resubmit_quality(mid, rid):
    auth.require_roles("QualityLab")
    machine, run = _need_machine_run(mid, rid)
    data = shape.body()
    shape.reject_unexpected_version(data)
    reels = _validate_reels(data)
    if run["quality_status"] != "REWORK":
        raise err("ERR_QUALITY_INVALID_STATE", "run quality axis is not REWORK")
    for rs in common.run_roll_sets(run["id"]):
        if rs["status"] not in ("WOUND", "SCRAPPED"):
            raise err("ERR_ROLL_SET_INVALID_STATE", "a rewind is still in flight")
    spec = common.need_spec(run["product_code"])
    run["reel_readings"] = reels
    run["off_spec_reel_count"] = calc.off_spec_reel_count(reels, spec)
    run["provisional_quality_index"] = calc.run_quality_index_provisional(reels, spec)
    run["quality_status"] = "PROVISIONAL"
    store.touch("production_runs", run)
    _ = machine
    return response.ok(common.view(run))


@bp.post("/paper-machines/<mid>/runs/<rid>/condemn")
def condemn_run(mid, rid):
    auth.require_roles("MillPlanner")
    machine, run = _need_machine_run(mid, rid)
    shape.reject_unexpected_version(shape.body())
    if run["quality_status"] != "HELD":
        raise err("ERR_QUALITY_INVALID_STATE", "run quality axis is not HELD")
    run["quality_status"] = "CONDEMNED"
    store.touch("production_runs", run)
    for rs in common.run_roll_sets(run["id"]):
        if rs["status"] in ("QUARANTINED", "REWOUND", "WOUND", "WRAPPED"):
            rs["status"] = "SCRAPPED"
            store.touch("roll_sets", rs)
            common.append_reject("MACHINE_BROKE", run["id"], rs["net_tons"])
    run["produced_tons"] = float(q(ZERO, 3))
    _ = machine
    return response.ok(common.view(run))
