"""Pilot plant bookings and stability studies (PRD §3.7)."""

from datetime import timedelta

from flask import Blueprint

import calc
import clock
import db
import errors as E
import middleware as M
import response as R
import validation as V
from routes import common
from services import core

bp = Blueprint("pilots", __name__)


def _extended_end(row):
    return core.dt_of(row, "window_end") + timedelta(
        minutes=row["effective_buffer_minutes"])


def _project_of_formulation(formulation):
    return db.projects.get(formulation["project_id"])


# ---------------------------------------------------------------------------
# booking a pilot run
# ---------------------------------------------------------------------------
@bp.post("/formulations/<formulation_id>/pilot-runs")
def create_pilot_run(formulation_id):
    M.authenticate("RnDLead")
    formulation = common.formulation(formulation_id)
    data = V.body()
    line_id = V.id_field(data, "pilot_line_id")
    start_raw, start_dt = V.datetime_field(data, "window_start")
    end_raw, end_dt = V.datetime_field(data, "window_end")
    planned_units = V.int_field(data, "planned_units", minimum=1)
    committed_cost = V.number_field(data, "committed_cost_usd", minimum=0)
    if end_dt <= start_dt:
        E.fail(E.ERR_INVALID_REQUEST, "window_end must be after window_start.")

    line = common.pilot_line(line_id)

    if formulation["status"] == "SUPERSEDED":
        E.fail(E.ERR_FORMULATION_INVALID_STATE,
               "A SUPERSEDED formulation takes no pilot bookings.")

    buffer_minutes = line["changeover_buffer_minutes"]
    if formulation["allergen_regime"] != line["allergen_regime"]:
        buffer_minutes *= 2
    new_end_ext = end_dt + timedelta(minutes=buffer_minutes)

    for other in db.rows(db.pilot_runs):
        if other["pilot_line_id"] != line["id"]:
            continue
        if other["status"] not in ("SCHEDULED", "RUNNING"):
            continue
        other_start = core.dt_of(other, "window_start")
        if start_dt < _extended_end(other) and other_start < new_end_ext:
            E.fail(E.ERR_PILOT_LINE_CONFLICT,
                   "The requested window overlaps a booked run on line %s."
                   % line["line_code"])

    project = _project_of_formulation(formulation)
    committed = core.committed_budget(project["id"])
    if committed + committed_cost > project["development_budget_cap_usd"]:
        E.fail(E.ERR_DEV_BUDGET_EXCEEDED,
               "Committing %s would push the ledger past the cap of %s."
               % (committed_cost, project["development_budget_cap_usd"]))

    row = core.new_row(db.pilot_runs, {
        "formulation_id": formulation["id"],
        "pilot_line_id": line["id"],
        "window_start": start_raw,
        "window_end": end_raw,
        "planned_units": planned_units,
        "committed_cost_usd": committed_cost,
        "effective_buffer_minutes": buffer_minutes,
        "actual_units": None,
        "yield_pct": None,
        "status": "SCHEDULED",
    })
    row["_dt_window_start"] = start_dt
    row["_dt_window_end"] = end_dt

    core.recompute_ledger(project)
    core.touch(formulation)
    return R.object_response(row, 201)


@bp.get("/pilot-runs")
def list_pilot_runs():
    M.reader()
    rows = M.apply_filters(db.rows(db.pilot_runs), {
        "formulation_id": "formulation_id",
        "pilot_line_id": "pilot_line_id",
        "status": "status",
    })
    rows = M.order(rows, [(lambda r: r["_dt_window_start"], False)])
    page, limit, offset, total = M.page(rows)
    return R.list_response(page, limit, offset, total)


@bp.get("/pilot-runs/<pilot_run_id>")
def read_pilot_run(pilot_run_id):
    M.reader()
    return R.object_response(common.pilot_run(pilot_run_id))


# ---------------------------------------------------------------------------
# run lifecycle
# ---------------------------------------------------------------------------
@bp.post("/pilot-runs/<pilot_run_id>/start")
def start_pilot_run(pilot_run_id):
    M.authenticate("RnDLead")
    row = common.pilot_run(pilot_run_id)
    if row["status"] != "SCHEDULED":
        E.fail(E.ERR_PILOT_RUN_INVALID_STATE,
               "Only a SCHEDULED run may be started; this one is %s."
               % row["status"])
    formulation = db.formulations.get(row["formulation_id"])
    if formulation is not None and formulation["status"] == "SUPERSEDED":
        E.fail(E.ERR_FORMULATION_INVALID_STATE,
               "The parent formulation is SUPERSEDED.")
    if clock.current_dt() < core.dt_of(row, "window_start"):
        E.fail(E.ERR_PILOT_RUN_NOT_DUE,
               "The run window has not opened yet.")

    core.apply(row, {"status": "RUNNING"})
    return R.object_response(row, 200)


@bp.post("/pilot-runs/<pilot_run_id>/complete")
def complete_pilot_run(pilot_run_id):
    M.authenticate("RnDLead")
    row = common.pilot_run(pilot_run_id)
    data = V.body()
    actual_units = V.int_field(data, "actual_units", minimum=0)

    if row["status"] != "RUNNING":
        E.fail(E.ERR_PILOT_RUN_INVALID_STATE,
               "Only a RUNNING run may be completed; this one is %s."
               % row["status"])

    yield_value = calc.yield_pct(actual_units, row["planned_units"])
    core.apply(row, {
        "status": "COMPLETED",
        "actual_units": actual_units,
        "yield_pct": yield_value,
    })

    formulation = db.formulations.get(row["formulation_id"])
    if formulation is not None:
        best = core.ZERO2
        for other in core.formulation_runs(formulation["id"]):
            if other["status"] == "COMPLETED" and other.get("yield_pct") is not None:
                if other["yield_pct"] > best:
                    best = other["yield_pct"]
        changes = {"best_pilot_yield_pct": calc.money(best)}
        passed = yield_value >= calc.PILOT_YIELD_FLOOR_PCT
        if passed:
            if formulation["status"] in ("DRAFT", "PILOT_FAILED"):
                changes["status"] = "PILOT_PASSED"
        elif formulation["status"] == "DRAFT":
            changes["status"] = "PILOT_FAILED"
        core.apply(formulation, changes)
        if passed:
            core.auto_approve(formulation["project_id"], "PILOT_SCALE_UP_REPORT")

    return R.object_response(row, 200)


@bp.post("/pilot-runs/<pilot_run_id>/cancel")
def cancel_pilot_run(pilot_run_id):
    M.authenticate("RnDLead")
    row = common.pilot_run(pilot_run_id)
    data = V.body()
    V.string_field(data, "reason", max_len=500)

    if row["status"] not in ("SCHEDULED", "RUNNING"):
        E.fail(E.ERR_PILOT_RUN_INVALID_STATE,
               "A %s run may not be cancelled." % row["status"])

    core.apply(row, {"status": "CANCELLED"})
    formulation = db.formulations.get(row["formulation_id"])
    if formulation is not None:
        project = _project_of_formulation(formulation)
        if project is not None:
            core.recompute_ledger(project)
    return R.object_response(row, 200)


# ---------------------------------------------------------------------------
# stability studies
# ---------------------------------------------------------------------------
@bp.post("/formulations/<formulation_id>/shelf-life-studies")
def create_study(formulation_id):
    M.authenticate("RnDLead")
    formulation = common.formulation(formulation_id)
    data = V.body()
    expected_version = V.int_field(data, "expected_formulation_version")
    duration_days = V.int_field(data, "duration_days", minimum=1)
    committed_cost = V.number_field(data, "committed_cost_usd", minimum=0)
    start_raw, start_dt = V.datetime_field(data, "start_at")

    if formulation["status"] == "SUPERSEDED":
        E.fail(E.ERR_FORMULATION_INVALID_STATE,
               "A SUPERSEDED formulation takes no stability studies.")
    if expected_version != formulation["version"]:
        E.fail(E.ERR_FORMULATION_VERSION_CONFLICT,
               "expected_formulation_version %s does not match stored version %s."
               % (expected_version, formulation["version"]))

    project = _project_of_formulation(formulation)
    committed = core.committed_budget(project["id"])
    if committed + committed_cost > project["development_budget_cap_usd"]:
        E.fail(E.ERR_DEV_BUDGET_EXCEEDED,
               "Committing %s would push the ledger past the cap of %s."
               % (committed_cost, project["development_budget_cap_usd"]))

    row = core.new_row(db.shelf_life_studies, {
        "formulation_id": formulation["id"],
        "duration_days": duration_days,
        "committed_cost_usd": committed_cost,
        "start_at": start_raw,
        "timepoints": [],
        "min_quality_score": None,
        "verdict": None,
        "status": "ACTIVE",
    })
    row["_dt_start_at"] = start_dt

    core.recompute_ledger(project)
    core.touch(formulation)
    return R.object_response(row, 201)


@bp.get("/formulations/<formulation_id>/shelf-life-studies")
def list_studies(formulation_id):
    M.reader()
    formulation = common.formulation(formulation_id)
    rows = core.formulation_studies(formulation["id"])
    rows = M.apply_filters(rows, {"status": "status"})
    rows = M.order(rows, [(lambda r: r["_dt_start_at"], False)])
    page, limit, offset, total = M.page(rows)
    return R.list_response(page, limit, offset, total)


@bp.get("/shelf-life-studies/<shelf_life_study_id>")
def read_study(shelf_life_study_id):
    M.reader()
    return R.object_response(common.study(shelf_life_study_id))


@bp.post("/shelf-life-studies/<shelf_life_study_id>/timepoints")
def append_timepoint(shelf_life_study_id):
    M.authenticate("RnDLead")
    row = common.study(shelf_life_study_id)
    data = V.body()
    day_index = V.int_field(data, "day_index", minimum=0)
    quality_score = V.number_field(data, "quality_score", minimum=0, maximum=100)

    if row["status"] != "ACTIVE":
        E.fail(E.ERR_STUDY_INVALID_STATE,
               "A %s study takes no further observations." % row["status"])
    for point in row["timepoints"]:
        if day_index <= point["day_index"]:
            E.fail(E.ERR_TIMEPOINT_OUT_OF_ORDER,
                   "day_index %d must exceed every recorded day_index."
                   % day_index)

    timepoints = list(row["timepoints"])
    timepoints.append({"day_index": day_index, "quality_score": quality_score})
    minimum = timepoints[0]["quality_score"]
    for point in timepoints[1:]:
        if point["quality_score"] < minimum:
            minimum = point["quality_score"]

    changes = {"timepoints": timepoints, "min_quality_score": minimum}
    verdict = None
    if quality_score < calc.STABILITY_ABSOLUTE_FLOOR:
        verdict = "FAIL"
    elif day_index >= row["duration_days"]:
        formulation = db.formulations.get(row["formulation_id"])
        target_days = formulation["target_shelf_life_days"] if formulation else 0
        verdict = calc.shelf_life_verdict(timepoints, minimum, target_days)

    if verdict is not None:
        changes["verdict"] = verdict
        changes["status"] = "PASSED" if verdict == "PASS" else "FAILED"

    core.apply(row, changes)

    if verdict == "PASS":
        formulation = db.formulations.get(row["formulation_id"])
        if formulation is not None:
            if formulation["status"] == "PILOT_PASSED":
                core.apply(formulation, {"status": "SHELF_LIFE_CLEARED"})
            core.auto_approve(formulation["project_id"], "SHELF_LIFE_REPORT")

    return R.object_response(row, 200)
