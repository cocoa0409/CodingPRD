"""RecallReminder: manual create, dismiss, list (PRD 3.10)."""
from flask import Blueprint, request

import db
import errors
import helpers
import response
from middleware import require

bp = Blueprint("recall_reminders", __name__)

REASONS = {"ROUTINE_SKIN_CHECK", "BIOPSY_FOLLOWUP"}


@bp.post("/recall-reminders")
@require("FrontDesk", "PracticeAdmin")
def create_recall():
    data = helpers.body()
    patient_id = helpers.require_str(data, "patient_id")
    reason = helpers.require_enum(data, "reason", REASONS)
    due_at = helpers.require_dt(data, "due_at")
    helpers.get_or_404(db.patients, patient_id, "patient")
    row = {
        "patient_id": patient_id,
        "biopsy_id": None,
        "reason": reason,
        "due_at": db.iso(due_at),
        "status": "PENDING",
    }
    db.stamp_new(row)
    db.recall_reminders[row["id"]] = row
    return response.created(row)


@bp.get("/recall-reminders/<rid>")
@require("FrontDesk", "PracticeAdmin", "Provider")
def get_recall(rid):
    row = helpers.get_or_404(db.recall_reminders, rid, "recall")
    return response.ok(row)


@bp.get("/recall-reminders")
@require("FrontDesk", "PracticeAdmin", "Provider")
def list_recalls():
    rows = list(db.recall_reminders.values())
    pid = request.args.get("patient_id")
    if pid is not None:
        rows = [r for r in rows if r["patient_id"] == pid]
    bid = request.args.get("biopsy_id")
    if bid is not None:
        rows = [r for r in rows if r["biopsy_id"] == bid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = helpers.paginate(rows)
    return response.listing(page, limit, offset, total)


@bp.post("/recall-reminders/<rid>/dismiss")
@require("FrontDesk")
def dismiss_recall(rid):
    r = helpers.get_or_404(db.recall_reminders, rid, "recall")
    if r["status"] != "PENDING":
        raise errors.bad_state("ERR_RECALL_BAD_STATE")
    r["status"] = "DISMISSED"
    db.touch(r)
    return response.ok(r)
