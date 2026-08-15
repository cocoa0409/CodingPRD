"""ScaleUpTrial endpoints: scheduling (formula DRAFT -> IN_TRIAL with the
zero-buffer touch-allowed pilot-cell rule), result recording (pass/fail
formula transitions), and cancellation."""
from flask import Blueprint, request

from db import STORE
from errors import (
    err,
    ERR_BATCH_EXCEEDS_CAPACITY,
    ERR_FORMULA_NOT_DRAFT,
    ERR_FORMULA_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_PILOT_CELL_CONFLICT,
    ERR_PILOT_CELL_NOT_FOUND,
    ERR_TRIAL_NOT_FOUND,
    ERR_TRIAL_NOT_SCHEDULED,
)
from middleware import require_roles
from response import paginate, success
from services.calc import pilot_cell_conflict
from services.core import find_or_404, new_record, serialize, sorted_created, touch
from util import as_bool, as_dt, as_int, as_str, body_json, req

bp = Blueprint("trials", __name__)


@bp.post("/copack/scale-up-trials")
def create_trial():
    require_roles("OpsAdmin")
    body = body_json()
    # Body FK existence (stage 4) precedes request-shape validation (stage 5).
    raw_formula_id = body.get("formula_id")
    if isinstance(raw_formula_id, str):
        find_or_404(STORE.formulas, raw_formula_id, ERR_FORMULA_NOT_FOUND, "formula")
    raw_cell_id = body.get("pilot_cell_id")
    if isinstance(raw_cell_id, str):
        find_or_404(STORE.pilot_cells, raw_cell_id, ERR_PILOT_CELL_NOT_FOUND, "pilot cell")
    formula_id = as_str(req(body, "formula_id"), "formula_id")
    formula = find_or_404(STORE.formulas, formula_id, ERR_FORMULA_NOT_FOUND, "formula")
    pilot_cell_id = as_str(req(body, "pilot_cell_id"), "pilot_cell_id")
    cell = find_or_404(STORE.pilot_cells, pilot_cell_id, ERR_PILOT_CELL_NOT_FOUND, "pilot cell")
    batch_size_units = as_int(req(body, "batch_size_units"), "batch_size_units")
    if batch_size_units < 1:
        raise err(ERR_INVALID_REQUEST, 400, "batch_size_units must be >= 1")
    scheduled_start = as_dt(req(body, "scheduled_start"), "scheduled_start")
    scheduled_end = as_dt(req(body, "scheduled_end"), "scheduled_end")
    if scheduled_end <= scheduled_start:
        raise err(ERR_INVALID_REQUEST, 400, "scheduled_end must be strictly after scheduled_start")
    # Stage 6: the formula must currently be DRAFT.
    if formula["status"] != "DRAFT":
        raise err(ERR_FORMULA_NOT_DRAFT, 409, "formula is not in DRAFT")
    # Stage 8 domain constraints: capacity, then the pilot-cell window rule.
    if batch_size_units > cell["max_batch_units"]:
        raise err(ERR_BATCH_EXCEEDS_CAPACITY, 409, "batch_size_units exceeds the pilot cell maximum")
    if pilot_cell_conflict(pilot_cell_id, scheduled_start, scheduled_end):
        raise err(ERR_PILOT_CELL_CONFLICT, 409, "trial window overlaps a SCHEDULED trial on this pilot cell")
    rec = new_record({
        "formula_id": formula_id,
        "pilot_cell_id": pilot_cell_id,
        "batch_size_units": batch_size_units,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "yield_units": None,
        "status": "SCHEDULED",
    })
    STORE.trials[rec["id"]] = rec
    formula["status"] = "IN_TRIAL"
    touch(formula)
    return success(serialize(rec), 201)


@bp.get("/copack/scale-up-trials")
def list_trials():
    require_roles("OpsAdmin", "QAReviewer")
    formula_id = request.args.get("formula_id")
    pilot_cell_id = request.args.get("pilot_cell_id")
    items = []
    for t in sorted_created(STORE.trials.values()):
        if formula_id is not None and t["formula_id"] != formula_id:
            continue
        if pilot_cell_id is not None and t["pilot_cell_id"] != pilot_cell_id:
            continue
        items.append(serialize(t))
    return paginate(items)


@bp.get("/copack/scale-up-trials/<tid>")
def get_trial(tid):
    require_roles("OpsAdmin", "QAReviewer")
    rec = find_or_404(STORE.trials, tid, ERR_TRIAL_NOT_FOUND, "trial")
    return success(serialize(rec))


@bp.post("/copack/scale-up-trials/<tid>/record-results")
def record_results(tid):
    require_roles("OpsAdmin")
    rec = find_or_404(STORE.trials, tid, ERR_TRIAL_NOT_FOUND, "trial")
    body = body_json()
    passed = as_bool(req(body, "passed"), "passed")
    yield_units = as_int(req(body, "yield_units"), "yield_units")
    if yield_units < 0:
        raise err(ERR_INVALID_REQUEST, 400, "yield_units must be >= 0")
    if rec["status"] != "SCHEDULED":
        raise err(ERR_TRIAL_NOT_SCHEDULED, 409, "trial is no longer SCHEDULED")
    formula = STORE.formulas.get(rec["formula_id"])
    if passed:
        rec["status"] = "PASSED"
        rec["yield_units"] = yield_units
        # ACID is letter-exempt and jumps straight to APPROVED; ACIDIFIED and
        # LOW_ACID wait in TRIAL_PASSED for a process-authority letter.
        if formula is not None and formula["status"] == "IN_TRIAL":
            formula["status"] = "APPROVED" if formula["process_category"] == "ACID" else "TRIAL_PASSED"
            touch(formula)
    else:
        rec["status"] = "FAILED"
        rec["yield_units"] = yield_units
        if formula is not None and formula["status"] == "IN_TRIAL":
            formula["status"] = "DRAFT"
            touch(formula)
    touch(rec)
    return success(serialize(rec))


@bp.post("/copack/scale-up-trials/<tid>/cancel")
def cancel_trial(tid):
    require_roles("OpsAdmin")
    rec = find_or_404(STORE.trials, tid, ERR_TRIAL_NOT_FOUND, "trial")
    if rec["status"] != "SCHEDULED":
        raise err(ERR_TRIAL_NOT_SCHEDULED, 409, "trial is no longer SCHEDULED")
    rec["status"] = "CANCELLED"
    touch(rec)
    formula = STORE.formulas.get(rec["formula_id"])
    if formula is not None and formula["status"] == "IN_TRIAL":
        formula["status"] = "DRAFT"
        touch(formula)
    return success(serialize(rec))
