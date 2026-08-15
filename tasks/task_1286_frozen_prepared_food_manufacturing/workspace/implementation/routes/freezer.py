"""Blast freezer cells and freezing cycles (PRD §3.4)."""

from datetime import timedelta

from flask import request

import services as svc
from db import STORE, bump, new_record
from errors import ApiError
from middleware import PLANT_ROLES, endpoint
from response import list_response, ok_object
from routes import bp
from serializers import cell_out, cycle_out
from util import (
    as_decimal,
    as_int,
    as_positive_int,
    as_string,
    body_dict,
    parse_dt,
    req_present,
)


# ---------------------------------------------------------------------------
# Cells
# ---------------------------------------------------------------------------

@bp.route("/plant/freezer-cells", methods=["POST"])
@endpoint({"PlantManager"})
def create_cell(user_id, role):
    body = body_dict(request.get_json(silent=True))
    cell_code = as_string(req_present(body, "cell_code"), "cell_code")
    capacity = as_positive_int(req_present(body, "capacity_kg"), "capacity_kg")
    min_load = as_positive_int(req_present(body, "min_load_kg"), "min_load_kg")
    pull_down = as_positive_int(
        req_present(body, "pull_down_kg_per_hour"), "pull_down_kg_per_hour"
    )
    sanitation = as_int(req_present(body, "sanitation_minutes"), "sanitation_minutes")
    if sanitation < 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'sanitation_minutes' must be >= 0")
    if min_load > capacity:
        raise ApiError("ERR_INVALID_REQUEST", "min_load_kg must be <= capacity_kg")
    for existing in STORE["cells"].values():
        if existing["cell_code"] == cell_code:
            raise ApiError("ERR_INVALID_REQUEST", "cell_code must be unique")

    rec = new_record()
    rec.update(
        cell_code=cell_code,
        capacity_kg=capacity,
        min_load_kg=min_load,
        pull_down_kg_per_hour=pull_down,
        sanitation_minutes=sanitation,
    )
    STORE["cells"][rec["id"]] = rec
    return ok_object(cell_out(rec), 201)


@bp.route("/plant/freezer-cells", methods=["GET"])
@endpoint(PLANT_ROLES)
def list_cells(user_id, role):
    return list_response(list(STORE["cells"].values()), cell_out)


@bp.route("/plant/freezer-cells/<cellId>", methods=["GET"])
@endpoint(PLANT_ROLES)
def get_cell(user_id, role, cellId):
    return ok_object(cell_out(svc.require_record("cells", cellId, "BlastFreezerCell")))


# ---------------------------------------------------------------------------
# Freezing cycles
# ---------------------------------------------------------------------------

@bp.route("/plant/production-batches/<batchId>/freezing-cycles", methods=["POST"])
@endpoint({"ProductionPlanner"})
def create_cycle(user_id, role, batchId):
    body = body_dict(request.get_json(silent=True))
    load_kg = as_positive_int(req_present(body, "load_kg"), "load_kg")
    entry_temp = as_decimal(req_present(body, "entry_temp_c"), "entry_temp_c")
    planned_start = parse_dt(req_present(body, "planned_start"), "planned_start")
    expected = as_int(req_present(body, "expected_batch_version"), "expected_batch_version")
    cell_id = body.get("cell_id")
    if cell_id is not None:
        cell_id = as_string(cell_id, "cell_id")

    batch = svc.require_record("batches", batchId, "ProductionBatch")
    cell = None
    if cell_id is not None:
        cell = svc.require_record("cells", cell_id, "BlastFreezerCell")
    # OCC (stage 7) before state (stage 8)
    if expected != batch["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", "expected_batch_version does not match the batch's current version"
        )
    if batch["status"] not in ("CREATED", "KITTED", "COOKED"):
        raise ApiError(
            "ERR_BATCH_STATE", "Cycles may be booked only for CREATED, KITTED or COOKED batches"
        )

    # Supersede: this batch's still-RESERVED cycles become VOIDED the moment the
    # new reservation is created; they are excluded from the window validation
    # below (so a superseded cycle never conflicts with its replacement) and are
    # actually voided only once every validation has passed (atomic commit).
    superseded = [c for c in svc.cycles_of_batch(batch["id"]) if c["status"] == "RESERVED"]
    exclude = {c["id"] for c in superseded}

    if cell is not None:
        hours = svc.freezer_cycle_hours(cell, load_kg, entry_temp)
        planned_end = planned_start + timedelta(hours=hours)
        # temporal windows (stage 10) before capacity constraints (stage 11)
        if svc.cell_window_conflict(cell, planned_start, planned_end, exclude):
            raise ApiError(
                "ERR_CELL_WINDOW_CONFLICT",
                "Cycle window collides with another RESERVED/IN_PROGRESS cycle on the cell",
            )
        if load_kg > cell["capacity_kg"]:
            raise ApiError("ERR_CAPACITY_EXCEEDED", "load_kg exceeds the cell's capacity_kg")
        if load_kg < cell["min_load_kg"]:
            raise ApiError("ERR_BELOW_MIN_LOAD", "load_kg is below the cell's min_load_kg")
    else:
        picked = svc.auto_select_cell(load_kg, entry_temp, planned_start, exclude)
        if picked is None:
            raise ApiError(
                "ERR_NO_CELL_AVAILABLE", "No cell satisfies the load and window constraints"
            )
        cell, hours, planned_end = picked

    for c in superseded:
        svc.void_reserved_cycle(c)

    rec = new_record()
    rec.update(
        batch_id=batch["id"],
        cell_id=cell["id"],
        load_kg=load_kg,
        entry_temp_c=entry_temp,
        planned_start=planned_start,
        required_hours=hours,
        planned_end=planned_end,
        actual_end=None,
        final_core_temp_c=None,
        status="RESERVED",
    )
    STORE["cycles"][rec["id"]] = rec
    bump(batch)
    return ok_object(cycle_out(rec), 201)


@bp.route("/plant/freezing-cycles", methods=["GET"])
@endpoint(PLANT_ROLES)
def list_cycles(user_id, role):
    cell_id = request.args.get("cell_id")
    batch_id = request.args.get("batch_id")
    status = request.args.get("status")
    recs = list(STORE["cycles"].values())
    if cell_id is not None:
        recs = [c for c in recs if c["cell_id"] == cell_id]
    if batch_id is not None:
        recs = [c for c in recs if c["batch_id"] == batch_id]
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    return list_response(recs, cycle_out)


@bp.route("/plant/freezing-cycles/<cycleId>", methods=["GET"])
@endpoint(PLANT_ROLES)
def get_cycle(user_id, role, cycleId):
    return ok_object(cycle_out(svc.require_record("cycles", cycleId, "FreezingCycle")))


@bp.route("/plant/freezing-cycles/<cycleId>/start", methods=["POST"])
@endpoint({"LineOperator"})
def start_cycle(user_id, role, cycleId):
    cycle = svc.require_record("cycles", cycleId, "FreezingCycle")
    if cycle["status"] != "RESERVED":
        raise ApiError("ERR_CYCLE_STATE", "Cycle cannot be started from %s" % cycle["status"])
    batch = svc.get_batch(cycle["batch_id"])
    if batch is None or batch["status"] != "COOKED":
        raise ApiError("ERR_BATCH_STATE", "Batch must be COOKED to start a cycle")
    cycle["status"] = "IN_PROGRESS"
    bump(cycle)
    return ok_object(cycle_out(cycle))


@bp.route("/plant/freezing-cycles/<cycleId>/complete", methods=["POST"])
@endpoint({"LineOperator"})
def complete_cycle(user_id, role, cycleId):
    body = body_dict(request.get_json(silent=True))
    actual_end = parse_dt(req_present(body, "actual_end"), "actual_end")
    final_temp = as_decimal(req_present(body, "final_core_temp_c"), "final_core_temp_c")

    cycle = svc.require_record("cycles", cycleId, "FreezingCycle")
    if cycle["status"] != "IN_PROGRESS":
        raise ApiError("ERR_CYCLE_STATE", "Cycle cannot be completed from %s" % cycle["status"])
    cycle["actual_end"] = actual_end
    cycle["final_core_temp_c"] = final_temp
    verified = svc.cycle_verified(cycle, actual_end, final_temp)
    cycle["status"] = "VERIFIED" if verified else "FAILED"
    bump(cycle)
    if verified:
        batch = svc.get_batch(cycle["batch_id"])
        if batch is not None and batch["status"] == "COOKED":
            batch["status"] = "FROZEN"
            bump(batch)
    # FAILED: the batch remains COOKED so a replacement cycle may be booked.
    return ok_object(cycle_out(cycle))


@bp.route("/plant/freezing-cycles/<cycleId>/void", methods=["POST"])
@endpoint({"ProductionPlanner"})
def void_cycle(user_id, role, cycleId):
    cycle = svc.require_record("cycles", cycleId, "FreezingCycle")
    if cycle["status"] != "RESERVED":
        raise ApiError("ERR_CYCLE_STATE", "Only a RESERVED cycle can be voided")
    svc.void_reserved_cycle(cycle)
    return ok_object(cycle_out(cycle))
