"""Time entry endpoints (logging, adjust, write-off, provisional summary)."""

import db
import errors
import helpers
import response
import serializers
from flask import Blueprint
from middleware import auth_required
from services import calculations


bp = Blueprint("time_entries", __name__)


def _ensure_not_archived(case):
    if case["status"] == "ARCHIVED":
        errors.raise_error(errors.ERR_CASE_ARCHIVED, "Case is archived.")


@bp.route("/cases/<cid>/time-entries", methods=["POST"])
@auth_required("PartnerLawyer", "SeniorLawyer", "JuniorLawyer")
def log_time_entry(cid):
    case = db.cases.get(cid)
    if case is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Case {cid} not found.")
    _ensure_not_archived(case)

    body = helpers.get_json_body()
    lawyer_id = helpers.require_str(body, "lawyer_id")
    task_label = body.get("task_label", "")
    if task_label is not None and not isinstance(task_label, str):
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "task_label must be a string.")
    minutes = helpers.require_int(body, "minutes", min_val=1, max_val=1440)
    billable = body.get("billable", True)
    if not isinstance(billable, bool):
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "billable must be a boolean.")

    lawyer = db.lawyers.get(lawyer_id)
    if lawyer is None:
        errors.raise_error(errors.ERR_REFERENCED_NOT_FOUND, f"Lawyer {lawyer_id} not found.")

    if case["posture"] == "FROZEN":
        errors.raise_error(
            errors.ERR_CASE_POSTURE_FROZEN,
            "Case is FROZEN; cannot log time entries.",
        )

    if case["status"] not in {"ACTIVE", "AWAITING_SETTLEMENT"}:
        # Without an explicit precondition in the PRD beyond posture, restrict
        # to a sensible business window (no logging on INTAKE / CLOSED / ON_HOLD).
        # PRD §3.6 implies entries are logged "by any lawyer rank with a payload"
        # but the case's lifecycle should be live; ON_HOLD is FROZEN already.
        errors.raise_error(
            errors.ERR_INVALID_STATE,
            "Time entries can only be logged on live cases (ACTIVE or AWAITING_SETTLEMENT).",
        )

    tid = db.new_id()
    common = helpers.common_create()
    entry = {
        "id": tid,
        "case_id": cid,
        "lawyer_id": lawyer_id,
        "task_label": task_label or "",
        "minutes": minutes,
        "billable": billable,
        "hourly_rate_cents_pinned": int(lawyer["hourly_rate_cents"]),
        "status": "LOGGED",
        "adjustment_minutes": 0,
        **common,
    }
    db.time_entries[tid] = entry
    return response.created(serializers.time_entry_dict(entry))


@bp.route("/time-entries/<tid>/adjust", methods=["PATCH"])
@auth_required("PartnerLawyer", "SeniorLawyer")
def adjust_time_entry(tid):
    entry = db.time_entries.get(tid)
    if entry is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"TimeEntry {tid} not found.")
    case = db.cases.get(entry["case_id"])
    if case is not None:
        _ensure_not_archived(case)
    body = helpers.get_json_body()
    helpers.check_occ(entry, body.get("version"))

    if "adjustment_minutes" not in body:
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "adjustment_minutes is required.")
    adj = body["adjustment_minutes"]
    if isinstance(adj, bool) or not isinstance(adj, int):
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "adjustment_minutes must be an integer.")

    if entry["status"] not in {"LOGGED", "ADJUSTED"}:
        errors.raise_error(
            errors.ERR_INVALID_STATE,
            "Only LOGGED or ADJUSTED entries can be adjusted.",
        )

    final = entry["minutes"] + adj
    if final < 0 or final > 1440:
        errors.raise_error(
            errors.ERR_TIME_ENTRY_ADJUSTMENT_INVALID,
            "minutes + adjustment_minutes must be in [0, 1440].",
        )

    entry["adjustment_minutes"] = adj
    entry["status"] = "ADJUSTED"
    helpers.bump(entry)
    return response.ok(serializers.time_entry_dict(entry))


@bp.route("/time-entries/<tid>/write-off", methods=["POST"])
@auth_required("PartnerLawyer")
def write_off_time_entry(tid):
    entry = db.time_entries.get(tid)
    if entry is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"TimeEntry {tid} not found.")
    case = db.cases.get(entry["case_id"])
    if case is not None:
        _ensure_not_archived(case)
    body = helpers.get_json_body()
    helpers.check_occ(entry, body.get("version"))

    if entry["status"] not in {"LOGGED", "ADJUSTED"}:
        errors.raise_error(
            errors.ERR_INVALID_STATE,
            "Only LOGGED or ADJUSTED entries can be written off.",
        )

    entry["status"] = "WRITTEN_OFF"
    helpers.bump(entry)
    return response.ok(serializers.time_entry_dict(entry))


@bp.route("/cases/<cid>/time-entries/summary", methods=["GET"])
@auth_required("PartnerLawyer", "SeniorLawyer")
def time_entries_summary(cid):
    case = db.cases.get(cid)
    if case is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Case {cid} not found.")
    provisional = calculations.compute_provisional_running_cost(cid)
    return response.ok({
        "case_id": cid,
        "provisional_running_cost_cents": provisional,
    })
