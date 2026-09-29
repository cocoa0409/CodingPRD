"""Step runs (dispatch, track-out, abort) and in-line metrology measurements."""
from flask import Blueprint, g

import calc
import clock
from auth import require
from db import db, need, new_row, ordered, touch
from errors import fail
from response import ok
from routes.common import matches, paged
from services import cascades
from util import r2, r4
from validate import body, q_enum, q_str, v_num, v_str

bp = Blueprint("production", __name__)

RUN_STATUSES = ("OPEN", "COMPLETED", "ABORTED")
CLASSIFICATIONS = ("IN_CONTROL", "WARN", "OUT_OF_CONTROL", "OUT_OF_SPEC")
RUN_READERS = ("Operator", "ProcessEngineer", "QualityManager", "YieldEngineer",
               "EquipmentEngineer", "FabPlanner")
MEASUREMENT_READERS = ("Operator", "ProcessEngineer", "QualityManager", "YieldEngineer")


def steps_of(flow_id):
    return [s for s in ordered(db.process_steps.values()) if s["flow_id"] == flow_id]


def _select_chamber(step, recipe, lot, now):
    """calculations.chamber_dispatch_score: lapse sweep, eligibility filter, ranking."""
    base = []
    for chamber in ordered(db.chambers.values()):
        equipment = db.equipment.get(chamber["equipment_id"])
        if equipment is None:
            continue
        if equipment["tool_type"] != recipe["tool_type"]:
            continue
        if chamber["qualified_recipe_id"] != step["recipe_id"]:
            continue
        base.append((chamber, equipment))

    # QUALIFIED -> QUAL_EXPIRED is observable even when the dispatch itself fails.
    for chamber, _equipment in base:
        if (chamber["qual_state"] == "QUALIFIED" and chamber["qual_expires_at"] is not None
                and now >= chamber["qual_expires_at"]):
            chamber["qual_state"] = "QUAL_EXPIRED"
            touch(chamber)

    candidates = []
    failures = []
    for chamber, equipment in base:
        reasons = set()
        if equipment["purge_until"] is not None and now <= equipment["purge_until"]:
            reasons.add("purge")
        if chamber["qual_state"] != "QUALIFIED":
            reasons.add("lapse" if chamber["qual_state"] == "QUAL_EXPIRED" else "qual")
        elif chamber["qual_expires_at"] is None or now >= chamber["qual_expires_at"]:
            reasons.add("lapse")
        if chamber["occupancy_state"] != "FREE":
            reasons.add("occupied")
        if chamber["particle_count"] > chamber["particle_limit"]:
            reasons.add("particle")
        if equipment["state"] not in ("IDLE", "PRODUCTIVE"):
            reasons.add("toolstate")
        if reasons:
            failures.append(reasons)
        else:
            candidates.append((chamber, equipment))

    if not candidates:
        if any(reasons == {"purge"} for reasons in failures):
            fail("ERR_PM_PURGE_ACTIVE",
                 "Every candidate chamber is inside its tool's post-PM purge interval")
        if any(reasons == {"lapse"} for reasons in failures):
            fail("ERR_CHAMBER_QUAL_EXPIRED",
                 "Every candidate chamber's qualification has lapsed")
        fail("ERR_NO_QUALIFIED_CHAMBER", "No qualified chamber is available for this step")

    scored = [
        (calc.dispatch_score(chamber, equipment, lot, now), chamber, equipment)
        for chamber, equipment in candidates
    ]
    scored.sort(key=lambda item: (-item[0], item[1]["chamber_code"]))
    return scored[0]


# ---------------------------------------------------------------- step runs

@bp.post("/fab/step-runs")
@require("Operator")
def create_step_run():
    data = body()
    lot_id = v_str(data, "lot_id")
    step_id = v_str(data, "step_id")
    operator_id = v_str(data, "operator_id")

    step = need(db.process_steps, step_id, "ERR_PROCESS_STEP_NOT_FOUND")
    lot = need(db.lots, lot_id, "ERR_LOT_NOT_FOUND")
    operator = need(db.operators, operator_id, "ERR_OPERATOR_NOT_FOUND")

    if g.user_id != operator["id"]:
        fail("ERR_OPERATOR_IDENTITY_MISMATCH",
             "X-User-ID does not match the operator tracking this lot in")
    if lot["flow_state"] not in ("RELEASED", "IN_PROCESS"):
        fail("ERR_LOT_INVALID_STATE",
             "Lot is %s; a step run requires RELEASED or IN_PROCESS" % lot["flow_state"])
    if lot["hold_state"] != "NONE":
        fail("ERR_LOT_ON_HOLD", "Lot is on %s" % lot["hold_state"])

    recipe = db.recipes[step["recipe_id"]]
    if recipe["status"] != "QUALIFIED":
        fail("ERR_RECIPE_RESTRICTED",
             "Recipe is %s (%s)" % (recipe["status"], recipe["restricted_reason"]))
    if operator["cert_status"] != "ACTIVE":
        fail("ERR_OPERATOR_CERT_INACTIVE",
             "Operator certification is %s" % operator["cert_status"])
    if operator["gown_state"] != "GOWNED":
        fail("ERR_OPERATOR_NOT_GOWNED", "Operator is not gowned")
    if recipe["tool_type"] not in operator["certified_tool_types"]:
        fail("ERR_OPERATOR_NOT_CERTIFIED",
             "Operator is not certified on %s tools" % recipe["tool_type"])
    if step["flow_id"] != lot["flow_id"]:
        fail("ERR_STEP_FLOW_MISMATCH", "The step does not belong to the lot's flow")

    nexts = [s["step_seq"] for s in steps_of(lot["flow_id"])
             if s["step_seq"] > lot["current_step_seq"]]
    if not nexts or step["step_seq"] != min(nexts):
        fail("ERR_STEP_SEQUENCE_VIOLATION",
             "Step %d is not the lot's next admissible step" % step["step_seq"])

    now = clock.now()
    score, chamber, equipment = _select_chamber(step, recipe, lot, now)
    if equipment["available_capacity_hours"] < step["standard_hours"]:
        fail("ERR_EQUIPMENT_CAPACITY_EXHAUSTED",
             "Tool has %.2f capacity hours left, the step needs %.2f"
             % (equipment["available_capacity_hours"], step["standard_hours"]))

    row = new_row({
        "lot_id": lot_id,
        "step_id": step_id,
        "operator_id": operator_id,
        "chamber_id": chamber["id"],
        "dispatch_score": score,
        "reserved_hours": step["standard_hours"],
        "actual_hours": None,
        "status": "OPEN",
        "tracked_in_at": now,
        "tracked_out_at": None,
    })
    db.step_runs[row["id"]] = row

    chamber["occupancy_state"] = "OCCUPIED"
    touch(chamber)

    equipment["available_capacity_hours"] = r2(
        equipment["available_capacity_hours"] - step["standard_hours"])
    if equipment["state"] == "IDLE":
        equipment["state"] = "PRODUCTIVE"
    touch(equipment)

    if lot["flow_state"] == "RELEASED":
        lot["flow_state"] = "IN_PROCESS"
        touch(lot)
    return ok(row, 201)


@bp.get("/fab/step-runs")
@require(*RUN_READERS)
def list_step_runs():
    filters = {
        "lot_id": q_str("lot_id"),
        "step_id": q_str("step_id"),
        "chamber_id": q_str("chamber_id"),
        "operator_id": q_str("operator_id"),
        "status": q_enum("status", RUN_STATUSES),
    }
    return paged([r for r in db.step_runs.values() if matches(r, filters)])


@bp.get("/fab/step-runs/<run_id>")
@require(*RUN_READERS)
def read_step_run(run_id):
    return ok(need(db.step_runs, run_id, "ERR_STEP_RUN_NOT_FOUND"))


@bp.post("/fab/step-runs/<run_id>/track-out")
@require("Operator")
def track_out(run_id):
    body()
    run = need(db.step_runs, run_id, "ERR_STEP_RUN_NOT_FOUND")
    if g.user_id != run["operator_id"]:
        fail("ERR_OPERATOR_IDENTITY_MISMATCH",
             "X-User-ID does not match the run's operator")
    if run["status"] != "OPEN":
        fail("ERR_STEP_RUN_NOT_OPEN", "Step run is %s, not OPEN" % run["status"])

    operator = db.operators[run["operator_id"]]
    if operator["cert_status"] != "ACTIVE":
        fail("ERR_OPERATOR_CERT_INACTIVE",
             "Operator certification is %s" % operator["cert_status"])
    if operator["gown_state"] != "GOWNED":
        fail("ERR_OPERATOR_NOT_GOWNED", "Operator is not gowned")

    step = db.process_steps[run["step_id"]]
    if step["metrology_required"] and not any(
            m["step_run_id"] == run["id"] for m in db.measurements.values()):
        fail("ERR_METROLOGY_MISSING",
             "This step requires at least one metrology measurement before track-out")

    now = clock.now()
    actual_hours = r2((now - run["tracked_in_at"]).total_seconds() / 3600.0)
    run["status"] = "COMPLETED"
    run["tracked_out_at"] = now
    run["actual_hours"] = actual_hours
    touch(run)

    chamber = db.chambers[run["chamber_id"]]
    chamber["occupancy_state"] = "FREE"
    touch(chamber)

    equipment = db.equipment[chamber["equipment_id"]]
    equipment["available_capacity_hours"] = r2(
        equipment["available_capacity_hours"] + run["reserved_hours"] - actual_hours)
    equipment["hours_since_pm"] = r2(equipment["hours_since_pm"] + actual_hours)
    touch(equipment)

    lot = db.lots[run["lot_id"]]
    lot["current_step_seq"] = step["step_seq"]
    last_seq = max(s["step_seq"] for s in steps_of(lot["flow_id"]))
    if lot["flow_state"] == "IN_PROCESS" and step["step_seq"] == last_seq:
        lot["flow_state"] = "AT_SORT"
    touch(lot)

    cascades.maybe_idle(equipment)
    return ok(run)


@bp.post("/fab/step-runs/<run_id>/abort")
@require("Operator")
def abort(run_id):
    data = body()
    v_str(data, "abort_reason")
    run = need(db.step_runs, run_id, "ERR_STEP_RUN_NOT_FOUND")
    if g.user_id != run["operator_id"]:
        fail("ERR_OPERATOR_IDENTITY_MISMATCH",
             "X-User-ID does not match the run's operator")
    if run["status"] != "OPEN":
        fail("ERR_STEP_RUN_NOT_OPEN", "Step run is %s, not OPEN" % run["status"])
    cascades.abort_run(run)
    return ok(run)


# -------------------------------------------------------------- measurements

@bp.post("/fab/measurements")
@require("Operator")
def create_measurement():
    data = body()
    step_run_id = v_str(data, "step_run_id")
    spc_chart_id = v_str(data, "spc_chart_id")
    measured_value = v_num(data, "measured_value")

    chart = need(db.spc_charts, spc_chart_id, "ERR_SPC_CHART_NOT_FOUND")
    run = need(db.step_runs, step_run_id, "ERR_STEP_RUN_NOT_FOUND")

    if g.user_id != run["operator_id"]:
        fail("ERR_OPERATOR_IDENTITY_MISMATCH",
             "X-User-ID does not match the run's operator")
    if run["status"] != "OPEN":
        fail("ERR_STEP_RUN_NOT_OPEN", "Step run is %s, not OPEN" % run["status"])
    if chart["status"] != "MONITORING":
        fail("ERR_SPC_CHART_SUSPENDED", "SPC chart is SUSPENDED")

    operator = db.operators[run["operator_id"]]
    if operator["cert_status"] != "ACTIVE":
        fail("ERR_OPERATOR_CERT_INACTIVE",
             "Operator certification is %s" % operator["cert_status"])
    if operator["gown_state"] != "GOWNED":
        fail("ERR_OPERATOR_NOT_GOWNED", "Operator is not gowned")

    if chart["step_id"] != run["step_id"]:
        fail("ERR_CHART_STEP_MISMATCH", "The chart does not monitor this run's step")
    step = db.process_steps[run["step_id"]]
    if not step["metrology_required"]:
        fail("ERR_METROLOGY_NOT_REQUIRED", "This step does not require metrology")

    measured_value = r2(measured_value)
    classification, deviation_sigma, run_rule, side, count = calc.classify_measurement(
        chart, measured_value)

    excursion_id = None
    chart["consecutive_same_side_count"] = count
    chart["last_side"] = side
    if classification in ("OUT_OF_CONTROL", "OUT_OF_SPEC") or run_rule:
        chart["violation_count"] = chart["violation_count"] + 1
        excursion = cascades.new_excursion(
            "SPC", r4(measured_value), spc_chart_id=chart["id"], lot_id=run["lot_id"],
            out_of_spec=(classification == "OUT_OF_SPEC"))
        excursion_id = excursion["id"]
    touch(chart)

    row = new_row({
        "step_run_id": step_run_id,
        "spc_chart_id": spc_chart_id,
        "excursion_id": excursion_id,
        "measured_value": measured_value,
        "classification": classification,
        "run_rule_triggered": run_rule,
        "deviation_sigma": deviation_sigma,
    }, versioned=False)
    db.measurements[row["id"]] = row
    return ok(row, 201)


@bp.get("/fab/measurements")
@require(*MEASUREMENT_READERS)
def list_measurements():
    filters = {
        "step_run_id": q_str("step_run_id"),
        "spc_chart_id": q_str("spc_chart_id"),
        "excursion_id": q_str("excursion_id"),
        "classification": q_enum("classification", CLASSIFICATIONS),
    }
    return paged([m for m in db.measurements.values() if matches(m, filters)])


@bp.get("/fab/measurements/<measurement_id>")
@require(*MEASUREMENT_READERS)
def read_measurement(measurement_id):
    return ok(need(db.measurements, measurement_id, "ERR_STEP_RUN_NOT_FOUND"))
