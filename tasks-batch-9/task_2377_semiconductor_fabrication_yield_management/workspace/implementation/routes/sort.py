"""Die sort runs and speed-grade binning."""
from flask import Blueprint

import calc
import clock
from auth import require
from db import db, need, new_row, touch
from errors import fail
from response import ok
from routes.common import matches, paged
from services import cascades
from util import r4
from validate import body, q_enum, q_str, v_int, v_list, v_num, v_str

bp = Blueprint("sort", __name__)

SORT_STATUSES = ("SORTED", "BINNED")
SIGNATURES = ("NONE", "EDGE_RING", "CENTER_CLUSTER", "SCRATCH_LINE", "PARAMETRIC_SHIFT")
READERS = ("YieldEngineer", "ProcessEngineer", "QualityManager", "FabPlanner")

WAFER_FIELDS = (
    ("wafer_slot", 1),
    ("tested_die", 1),
    ("good_die", 0),
    ("edge_ring_fails", 0),
    ("center_cluster_fails", 0),
    ("scratch_line_fails", 0),
    ("parametric_shift_fails", 0),
)


def _validate_wafer_shape(rows):
    """Per-element shape errors are ERR_VALIDATION (priority 3)."""
    for index, element in enumerate(rows):
        if not isinstance(element, dict):
            fail("ERR_VALIDATION", "wafer_results[%d] must be an object" % index)
        for key, minimum in WAFER_FIELDS:
            if key not in element or element[key] is None:
                fail("ERR_VALIDATION", "wafer_results[%d].%s is required" % (index, key))
            value = element[key]
            if isinstance(value, bool) or not isinstance(value, int):
                fail("ERR_VALIDATION",
                     "wafer_results[%d].%s must be an integer" % (index, key))
            if value < minimum:
                fail("ERR_VALIDATION",
                     "wafer_results[%d].%s must be >= %d" % (index, key, minimum))


def _validate_wafer_consistency(rows):
    """Arithmetic inconsistency is ERR_WAFER_RESULT_INCONSISTENT (priority 43)."""
    if not rows:
        fail("ERR_WAFER_RESULT_INCONSISTENT", "wafer_results must be non-empty")
    for index, element in enumerate(rows):
        if element["good_die"] > element["tested_die"]:
            fail("ERR_WAFER_RESULT_INCONSISTENT",
                 "wafer_results[%d]: good_die exceeds tested_die" % index)
        fails = (element["edge_ring_fails"] + element["center_cluster_fails"]
                 + element["scratch_line_fails"] + element["parametric_shift_fails"])
        if fails != element["tested_die"] - element["good_die"]:
            fail("ERR_WAFER_RESULT_INCONSISTENT",
                 "wafer_results[%d]: fail counts do not sum to tested_die - good_die" % index)


@bp.post("/fab/die-sort-runs")
@require("YieldEngineer")
def create_sort_run():
    data = body()
    lot_id = v_str(data, "lot_id")
    gross_die_per_wafer = v_int(data, "gross_die_per_wafer", minimum=1)
    baseline_yield = v_num(data, "baseline_yield", gt=0, le=1)
    wafer_results = v_list(data, "wafer_results")
    _validate_wafer_shape(wafer_results)

    lot = need(db.lots, lot_id, "ERR_LOT_NOT_FOUND")
    if lot["flow_state"] != "AT_SORT":
        fail("ERR_LOT_INVALID_STATE", "Lot is %s, not AT_SORT" % lot["flow_state"])
    if lot["hold_state"] != "NONE":
        fail("ERR_LOT_ON_HOLD", "Lot is on %s" % lot["hold_state"])
    _validate_wafer_consistency(wafer_results)

    baseline_yield = r4(baseline_yield)
    sort_yield, good_die_total, yield_loss_ratio = calc.sort_yield_stage(
        baseline_yield, wafer_results)
    signature = calc.dominant_signature(wafer_results)

    row = new_row({
        "lot_id": lot_id,
        "gross_die_per_wafer": gross_die_per_wafer,
        "baseline_yield": baseline_yield,
        "premium_target_die": 0,
        "standard_target_die": 0,
        "wafer_results": wafer_results,
        "sort_yield": sort_yield,
        "yield_loss_ratio": yield_loss_ratio,
        "dominant_signature": signature,
        "good_die_total": good_die_total,
        "premium_die": 0,
        "standard_die": 0,
        "value_die": 0,
        "status": "SORTED",
    })
    db.die_sort_runs[row["id"]] = row

    if yield_loss_ratio >= calc.SORT_EXCURSION_THRESHOLD:
        cascades.new_excursion("DIE_SORT", yield_loss_ratio, die_sort_run_id=row["id"],
                               lot_id=lot_id, failure_signature=signature)
    return ok(row, 201)


@bp.get("/fab/die-sort-runs")
@require(*READERS)
def list_sort_runs():
    filters = {
        "lot_id": q_str("lot_id"),
        "status": q_enum("status", SORT_STATUSES),
        "dominant_signature": q_enum("dominant_signature", SIGNATURES),
    }
    return paged([r for r in db.die_sort_runs.values() if matches(r, filters)])


@bp.get("/fab/die-sort-runs/<sort_run_id>")
@require(*READERS)
def read_sort_run(sort_run_id):
    return ok(need(db.die_sort_runs, sort_run_id, "ERR_SORT_RUN_NOT_FOUND"))


@bp.post("/fab/die-sort-runs/<sort_run_id>/bin")
@require("YieldEngineer")
def bin_sort_run(sort_run_id):
    data = body()
    premium_target_die = v_int(data, "premium_target_die", minimum=0)
    standard_target_die = v_int(data, "standard_target_die", minimum=0)
    run = need(db.die_sort_runs, sort_run_id, "ERR_SORT_RUN_NOT_FOUND")

    if run["status"] != "SORTED":
        fail("ERR_SORT_RUN_ALREADY_BINNED", "Die sort run is %s, not SORTED" % run["status"])
    lot = db.lots[run["lot_id"]]
    if lot["flow_state"] != "AT_SORT":
        fail("ERR_LOT_INVALID_STATE", "Lot is %s, not AT_SORT" % lot["flow_state"])

    premium, standard, value = calc.speed_grade_waterfall(
        run["good_die_total"], premium_target_die, standard_target_die)
    run["premium_target_die"] = premium_target_die
    run["standard_target_die"] = standard_target_die
    run["premium_die"] = premium
    run["standard_die"] = standard
    run["value_die"] = value
    run["status"] = "BINNED"
    touch(run)

    lot["flow_state"] = "COMPLETED"
    lot["completed_at"] = clock.now()
    if lot["released_at"] is not None:
        lot["actual_cycle_time_days"] = calc.chronological_cycle_time(lot)
    touch(lot)
    return ok(run)
