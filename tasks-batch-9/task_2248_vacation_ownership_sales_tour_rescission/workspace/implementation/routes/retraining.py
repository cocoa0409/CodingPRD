"""Compliance retraining assignments (PRD 3.9)."""

from flask import Blueprint

import auth
import calc
import derive
import errors
import validators
from envelope import created, listing, ok
from errors import fail
from helpers import collect, get_rep, get_retraining, page
from store import db

bp = Blueprint("retraining", __name__)

ASSIGNMENT_STATUSES = ("ASSIGNED", "IN_PROGRESS", "COMPLETED", "FAILED")


@bp.post("/retraining-assignments")
def create_assignment():
    auth.require(auth.COMPLIANCE_OFFICER)
    data = validators.body()
    rep_id = validators.identifier(data, "rep_id")
    reason = validators.enum(data, "trigger_reason", calc.RETRAINING_REASONS)
    module_count = validators.integer(
        data,
        "required_module_count",
        1,
        10,
        required=False,
        default=calc.AUTO_RETRAINING_MODULE_COUNT,
    )
    expected_version = validators.integer(data, "expected_representative_version", 1)

    rep = get_rep(rep_id)
    if rep["version"] != expected_version:
        fail(
            errors.ERR_STALE_REPRESENTATIVE_VERSION,
            "representative version is %d" % rep["version"],
        )
    if derive.open_assignment(rep["id"], reason) is not None:
        fail(
            errors.ERR_RETRAINING_ALREADY_ACTIVE,
            "an assignment with this trigger_reason is already active",
        )

    rate = rep["cancellation_rate"] if reason == "CANCELLATION_RATE_BREACH" else None
    assignment = derive.new_assignment(rep, reason, module_count, cancellation_rate=rate)
    # A successful create always advances the representative's version.
    derive.touch(rep)
    return created(assignment)


@bp.post("/retraining-assignments/<assignment_id>/start")
def start_assignment(assignment_id):
    auth.require(auth.COMPLIANCE_OFFICER)
    assignment = get_retraining(assignment_id)
    if assignment["status"] != "ASSIGNED":
        fail(errors.ERR_INVALID_RETRAINING_STATE, "assignment is not ASSIGNED")

    derive.setf(assignment, "status", "IN_PROGRESS")
    derive.setf(assignment, "started_at", db.now())
    rep = db.reps.get(assignment["rep_id"])
    if rep is not None:
        if rep["status"] == "ACTIVE":
            derive.setf(rep, "status", "RETRAINING")
        derive.recompute_gallery_reps(db.galleries.get(rep["gallery_id"]))
    return ok(assignment)


@bp.post("/retraining-assignments/<assignment_id>/close")
def close_assignment(assignment_id):
    auth.require(auth.COMPLIANCE_OFFICER)
    data = validators.body()
    outcome = validators.enum(data, "outcome", ("COMPLETE", "FAIL"))
    modules_completed = validators.integer(data, "modules_completed", 0)
    assignment = get_retraining(assignment_id)

    if assignment["status"] != "IN_PROGRESS":
        fail(errors.ERR_INVALID_RETRAINING_STATE, "assignment is not IN_PROGRESS")
    if outcome == "COMPLETE" and modules_completed < assignment["required_module_count"]:
        fail(
            errors.ERR_MODULE_COUNT_SHORTFALL,
            "modules_completed is below required_module_count",
        )

    derive.setf(assignment, "modules_completed", modules_completed)
    derive.setf(assignment, "closed_at", db.now())
    if outcome == "FAIL":
        derive.setf(assignment, "status", "FAILED")
        return ok(assignment)

    derive.setf(assignment, "status", "COMPLETED")
    rep = db.reps.get(assignment["rep_id"])
    if rep is not None:
        # CASCADE STEP 1
        derive.setf(rep, "compliance_strike_count", 0)
        # CASCADE STEP 2
        if not derive.has_open_assignment(rep["id"]):
            derive.setf(rep, "status", "ACTIVE")
        # CASCADE STEP 3
        derive.recompute_gallery_reps(db.galleries.get(rep["gallery_id"]))
    return ok(assignment)


@bp.post("/retraining-assignments/<assignment_id>/reassign")
def reassign_assignment(assignment_id):
    auth.require(auth.COMPLIANCE_OFFICER)
    assignment = get_retraining(assignment_id)
    if assignment["status"] != "FAILED":
        fail(errors.ERR_INVALID_RETRAINING_STATE, "assignment is not FAILED")
    if assignment["cycle_index"] >= calc.RETRAINING_CYCLE_LIMIT:
        fail(errors.ERR_INVALID_RETRAINING_STATE, "the retraining cycle cap is reached")

    derive.setf(assignment, "cycle_index", assignment["cycle_index"] + 1)
    derive.setf(assignment, "assigned_at", db.now())
    derive.setf(assignment, "modules_completed", 0)
    derive.setf(assignment, "started_at", None)
    derive.setf(assignment, "closed_at", None)
    derive.setf(assignment, "status", "ASSIGNED")
    return ok(assignment)


@bp.get("/retraining-assignments/<assignment_id>")
def read_assignment(assignment_id):
    auth.require_any()
    return ok(get_retraining(assignment_id))


@bp.get("/retraining-assignments")
def list_assignments():
    auth.require_any()
    limit, offset = page()
    rows = collect(
        db.retrainings,
        (
            ("rep_id", "rep_id"),
            ("trigger_reason", "trigger_reason", calc.RETRAINING_REASONS),
            ("status", "status", ASSIGNMENT_STATUSES),
        ),
    )
    return listing(rows, limit, offset)
