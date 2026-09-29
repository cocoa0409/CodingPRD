from datetime import timedelta

from flask import Blueprint

import auth
import calc
import common
import response
import shape
import store
from errors import err
from shape import parse_dt

bp = Blueprint("machines", __name__)


@bp.post("/paper-machines")
def create_machine():
    auth.require_roles("MillPlanner")
    data = shape.body()
    shape.reject_unexpected_version(data)
    row = {
        "name": shape.get_str(data, "name", min_len=1, max_len=20),
        "wire_width_mm": shape.get_int(data, "wire_width_mm", minimum=1000, maximum=8000),
        "max_tons_per_hour": shape.get_num(data, "max_tons_per_hour", exclusive_min=0, places=2),
        "changeover_buffer_minutes": shape.get_int(data, "changeover_buffer_minutes", minimum=0, maximum=240),
        "steam_tph_per_ton": shape.get_num(data, "steam_tph_per_ton", exclusive_min=0, places=3),
        "current_product_code": None,
        "status": "RUNNABLE",
    }
    common.unique_or_conflict("paper_machines", "name", row["name"])
    store.insert("paper_machines", row)
    return response.ok(common.view(row), 201)


@bp.get("/paper-machines/<mid>")
def get_machine(mid):
    auth.require_roles("MillPlanner", "MachineOperator", "EnergyManager")
    return response.ok(common.view(common.need("paper_machines", mid, "ERR_MACHINE_NOT_FOUND")))


@bp.patch("/paper-machines/<mid>/status")
def patch_machine_status(mid):
    auth.require_roles("MillPlanner")
    machine = common.need("paper_machines", mid, "ERR_MACHINE_NOT_FOUND")
    data = shape.body()
    status = shape.get_enum(data, "status", ["RUNNABLE", "DOWN"])
    expected = shape.get_version(data, "expected_machine_version")
    if expected != machine["version"]:
        raise err("ERR_STALE_MACHINE_VERSION", "expected_machine_version is stale")
    machine["status"] = status
    store.touch("paper_machines", machine)
    return response.ok(common.view(machine))


# ------------------------------------------------------- grade changes ---
@bp.post("/paper-machines/<mid>/grade-changes")
def plan_grade_change(mid):
    auth.require_roles("MillPlanner")
    machine = common.need("paper_machines", mid, "ERR_MACHINE_NOT_FOUND")
    data = shape.body()
    from_id = shape.get_str(data, "from_run_id")
    to_id = shape.get_str(data, "to_run_id")
    expected = shape.get_version(data, "expected_machine_version")
    from_run = store.get("production_runs", from_id)
    if from_run is None or from_run["machine_id"] != machine["id"]:
        raise err("ERR_LINK_TARGET_NOT_FOUND", "from_run_id does not resolve to a run of this machine")
    to_run = store.get("production_runs", to_id)
    if to_run is None or to_run["machine_id"] != machine["id"]:
        raise err("ERR_LINK_TARGET_NOT_FOUND", "to_run_id does not resolve to a run of this machine")
    if expected != machine["version"]:
        raise err("ERR_STALE_MACHINE_VERSION", "expected_machine_version is stale")
    from_spec = common.need_spec(from_run["product_code"])
    to_spec = common.need_spec(to_run["product_code"])
    res = calc.grade_change_transition_waste(from_spec, to_spec, machine)
    gap_minutes = int((parse_dt(to_run["window_start"]) - parse_dt(from_run["window_end"]))
                      .total_seconds() // 60)
    if gap_minutes < res["transition_minutes"]:
        raise err("ERR_TRANSITION_GAP_TOO_SHORT",
                  "gap of %d minutes is shorter than the required %d"
                  % (gap_minutes, res["transition_minutes"]))
    row = {
        "machine_id": machine["id"],
        "from_run_id": from_run["id"],
        "to_run_id": to_run["id"],
        "from_product_code": from_run["product_code"],
        "to_product_code": to_run["product_code"],
        "transition_waste_tons": res["transition_waste_tons"],
        "transition_minutes": res["transition_minutes"],
        "status": "PLANNED",
    }
    store.insert("grade_changes", row)
    store.touch("paper_machines", machine)
    return response.ok(common.view(row), 201)


@bp.get("/grade-changes/<gid>")
def get_grade_change(gid):
    auth.require_roles("MillPlanner", "MachineOperator")
    return response.ok(common.view(common.need("grade_changes", gid, "ERR_GRADE_CHANGE_NOT_FOUND")))


@bp.get("/grade-changes")
def list_grade_changes():
    auth.require_roles("MillPlanner", "MachineOperator")
    limit, offset = shape.pagination()
    rows = common.filtered("grade_changes", {
        "machine_id": "machine_id",
        "status": "status",
        "from_run_id": "from_run_id",
        "to_run_id": "to_run_id",
    })
    return response.ok_list(common.views(shape.paginate(rows, limit, offset)), limit, offset, len(rows))


@bp.post("/grade-changes/<gid>/void")
def void_grade_change(gid):
    auth.require_roles("MillPlanner")
    gc = common.need("grade_changes", gid, "ERR_GRADE_CHANGE_NOT_FOUND")
    shape.reject_unexpected_version(shape.body())
    if gc["status"] != "PLANNED":
        raise err("ERR_ENV_RECORD_INVALID_STATE", "grade change is not PLANNED")
    gc["status"] = "VOIDED"
    store.touch("grade_changes", gc)
    return response.ok(common.view(gc))


# ---------------------------------------------------- run scheduling ---
def closed_intervals_intersect(a_start, a_end, b_start, b_end):
    return a_start <= b_end and a_end >= b_start


@bp.post("/paper-machines/<mid>/runs")
def create_run(mid):
    auth.require_roles("MillPlanner")
    machine = common.need("paper_machines", mid, "ERR_MACHINE_NOT_FOUND")
    data = shape.body()
    product = shape.get_str(data, "product_code")
    batch_id = shape.get_str(data, "pulp_batch_id")
    ws = shape.get_dt(data, "window_start")
    we = shape.get_dt(data, "window_end")
    draw = shape.get_num(data, "pulp_draw_tons", exclusive_min=0, places=3)
    expected = shape.get_version(data, "expected_machine_version")
    if we <= ws:
        raise err("ERR_INVALID_WINDOW", "window_end must be strictly after window_start")
    spec = common.need_spec(product)
    batch = store.get("pulp_batches", batch_id)
    if batch is None:
        raise err("ERR_FURNISH_REFERENCE_NOT_FOUND", "pulp_batch_id does not resolve")
    if expected != machine["version"]:
        raise err("ERR_STALE_MACHINE_VERSION", "expected_machine_version is stale")
    if machine["status"] == "DOWN":
        raise err("ERR_RUN_INVALID_STATE", "machine is DOWN")
    if batch["target_product_code"] != product:
        raise err("ERR_PRODUCT_MISMATCH", "pulp batch target product differs from the run's product")
    buf = timedelta(minutes=int(machine["changeover_buffer_minutes"]))
    wide_start = ws - buf
    wide_end = we + buf
    for other in store.all_rows("production_runs"):
        if other["machine_id"] != machine["id"]:
            continue
        if other["run_status"] not in ("SCHEDULED", "RUNNING"):
            continue
        o_start = parse_dt(other["window_start"])
        o_end = parse_dt(other["window_end"])
        if closed_intervals_intersect(wide_start, wide_end, o_start, o_end):
            raise err("ERR_MACHINE_WINDOW_CONFLICT", "run window collides on this machine")
    row = {
        "machine_id": machine["id"],
        "product_code": product,
        "pulp_batch_id": batch["id"],
        "window_start": shape.iso(ws),
        "window_end": shape.iso(we),
        "pulp_draw_tons": draw,
        "produced_tons": 0.0,
        "broke_tons": 0,
        "reel_readings": None,
        "provisional_quality_index": None,
        "certified_quality_index": None,
        "off_spec_reel_count": 0,
        "started_by_user_id": None,
        "certified_by_user_id": None,
        "run_status": "SCHEDULED",
        "quality_status": "PENDING",
    }
    store.insert("production_runs", row)
    store.touch("paper_machines", machine)
    _ = spec
    return response.ok(common.view(row), 201)


@bp.get("/paper-machines/<mid>/runs")
def list_machine_runs(mid):
    auth.require_roles("MillPlanner", "MachineOperator", "QualityLab")
    machine = common.need("paper_machines", mid, "ERR_MACHINE_NOT_FOUND")
    limit, offset = shape.pagination()
    rows = common.filtered("production_runs", {
        "run_status": "run_status",
        "quality_status": "quality_status",
    }, extra=lambda r: r["machine_id"] == machine["id"])
    return response.ok_list(common.views(shape.paginate(rows, limit, offset)), limit, offset, len(rows))
