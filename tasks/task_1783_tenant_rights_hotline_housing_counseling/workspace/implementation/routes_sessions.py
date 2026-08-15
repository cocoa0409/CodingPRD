"""Call sessions: triage, assignment, activation, interpreter coordination."""

from flask import Blueprint, request

from db import store, now
from errors import (
    raise_err, invalid_request, not_found, invalid_state,
    ERR_CALLER_PII_PURGED, ERR_COUNSELOR_INACTIVE, ERR_CERTIFICATION_EXPIRED,
    ERR_TRAINING_NOT_CURRENT, ERR_LANGUAGE_UNSUPPORTED, ERR_SCRIPT_NOT_PUBLISHED,
    ERR_INTERPRETER_LANGUAGE_MISMATCH, ERR_INTERPRETER_OVERLAP,
    ERR_INTERPRETER_PREVIOUSLY_FAILED,
)
from middleware import require_roles
from response import ok_object, ok_list
from serializers import session_out
from services import (
    make_record, bump, current_published_script, interpreter_window_conflict,
    ISSUE_CATEGORIES,
)
from util import (
    get_payload, check_unknown, require, as_str, as_enum, parse_dt, page_of,
    query_enum,
)

bp = Blueprint("sessions", __name__)

SESSION_STATUSES = ("QUEUED", "ASSIGNED", "ACTIVE", "WRAPPED_UP", "DROPPED", "ABANDONED")
INTERP_STATUSES = ("NOT_REQUIRED", "REQUESTED", "CONNECTED", "FAILED")
TERMINAL_SESSION = ("WRAPPED_UP", "DROPPED", "ABANDONED")
SESSION_ROLES = ("Counselor", "HotlineSupervisor")


@bp.route("/hotline/sessions", methods=["POST"])
def create_session():
    require_roles("Anonymous")
    data = get_payload()
    check_unknown(data, {"caller_id", "jurisdiction_id", "issue_category", "triage_notes"})
    caller_id = as_str(require(data, "caller_id"), "caller_id")
    jurisdiction_id = as_str(require(data, "jurisdiction_id"), "jurisdiction_id")
    issue_category = as_enum(require(data, "issue_category"), "issue_category", ISSUE_CATEGORIES)
    triage_notes = data.get("triage_notes")
    if triage_notes is not None:
        as_str(triage_notes, "triage_notes")
    caller = store.callers.get(caller_id)
    if caller is None:
        invalid_request("caller_id does not reference an existing caller")
    if jurisdiction_id not in store.jurisdictions:
        invalid_request("jurisdiction_id does not reference an existing jurisdiction")
    if caller["pii_purged"]:
        raise_err(ERR_CALLER_PII_PURGED, "caller PII has been purged; intake refused")
    rec = make_record({
        "caller_id": caller_id,
        "jurisdiction_id": jurisdiction_id,
        "issue_category": issue_category,
        "triage_notes": triage_notes,
        "counselor_id": None,
        "interpreter_id": None,
        "scheduled_start_at": None,
        "scheduled_end_at": None,
        "actual_start_at": None,
        "actual_end_at": None,
        "queue_wait_seconds": 0,
        "session_status": "QUEUED",
        "interpretation_status": "NOT_REQUIRED",
        "pinned_script_id": None,
        "failed_interpreter_ids": [],
    })
    store.sessions[rec["id"]] = rec
    return ok_object(session_out(rec), status=201)


@bp.route("/hotline/sessions/<sid>", methods=["GET"])
def get_session(sid):
    require_roles(*SESSION_ROLES)
    rec = store.sessions.get(sid)
    if rec is None:
        not_found("session not found")
    return ok_object(session_out(rec))


@bp.route("/hotline/sessions", methods=["GET"])
def list_sessions():
    require_roles(*SESSION_ROLES)
    caller_id = request.args.get("caller_id")
    counselor_id = request.args.get("counselor_id")
    interpreter_id = request.args.get("interpreter_id")
    jurisdiction_id = request.args.get("jurisdiction_id")
    pinned_script_id = request.args.get("pinned_script_id")
    session_status = query_enum("session_status", SESSION_STATUSES)
    recs = list(store.sessions.values())
    if caller_id is not None:
        recs = [r for r in recs if r["caller_id"] == caller_id]
    if counselor_id is not None:
        recs = [r for r in recs if r["counselor_id"] == counselor_id]
    if interpreter_id is not None:
        recs = [r for r in recs if r["interpreter_id"] == interpreter_id]
    if jurisdiction_id is not None:
        recs = [r for r in recs if r["jurisdiction_id"] == jurisdiction_id]
    if pinned_script_id is not None:
        recs = [r for r in recs if r["pinned_script_id"] == pinned_script_id]
    if session_status is not None:
        recs = [r for r in recs if r["session_status"] == session_status]
    page, total, limit, offset = page_of(recs)
    return ok_list([session_out(r) for r in page], total, limit, offset)


@bp.route("/hotline/sessions/<sid>/state", methods=["POST"])
def transition_session(sid):
    role, uid = require_roles(*SESSION_ROLES)
    rec = store.sessions.get(sid)
    if rec is None:
        not_found("session not found")
    data = get_payload()
    check_unknown(data, {"to_status", "counselor_id"})
    to_status = as_enum(require(data, "to_status"), "to_status", SESSION_STATUSES)
    current = rec["session_status"]

    if to_status == "ASSIGNED":
        counselor_id = data.get("counselor_id")
        if counselor_id is None:
            invalid_request("counselor_id is required for ASSIGNED")
        as_str(counselor_id, "counselor_id")
        counselor = store.counselors.get(counselor_id)
        if counselor is None:
            invalid_request("counselor_id does not reference an existing counselor")
        jurisdiction = store.jurisdictions[rec["jurisdiction_id"]]
        if (
            jurisdiction["code"] not in counselor["certified_jurisdiction_codes"]
            or rec["issue_category"] not in counselor["certified_categories"]
        ):
            invalid_request("counselor certification scope does not cover this session")
        if current != "QUEUED":
            invalid_state("session transition %s -> ASSIGNED is not allowed" % current)
        if counselor["status"] != "ACTIVE":
            raise_err(ERR_COUNSELOR_INACTIVE, "counselor is not ACTIVE")
        if counselor["certification_expires_at"] <= now():
            raise_err(ERR_CERTIFICATION_EXPIRED, "counselor certification has expired")
        script = current_published_script(rec["jurisdiction_id"], rec["issue_category"])
        if script is None or script["id"] not in counselor["trained_script_ids"]:
            raise_err(ERR_TRAINING_NOT_CURRENT,
                      "counselor is not trained on the current published script")
        rec["counselor_id"] = counselor_id
        rec["session_status"] = "ASSIGNED"
        bump(rec)
        return ok_object(session_out(rec))

    if to_status == "ACTIVE":
        if current != "ASSIGNED":
            invalid_state("session transition %s -> ACTIVE is not allowed" % current)
        if rec["interpretation_status"] == "REQUESTED":
            invalid_state("cannot start a session while an interpreter request is pending")
        counselor = store.counselors.get(rec["counselor_id"])
        if counselor is None or counselor["status"] != "ACTIVE":
            raise_err(ERR_COUNSELOR_INACTIVE, "assigned counselor is not ACTIVE")
        if counselor["certification_expires_at"] <= now():
            raise_err(ERR_CERTIFICATION_EXPIRED, "counselor certification has expired")
        script = current_published_script(rec["jurisdiction_id"], rec["issue_category"])
        if script is not None and script["id"] not in counselor["trained_script_ids"]:
            raise_err(ERR_TRAINING_NOT_CURRENT,
                      "counselor is not trained on the current published script")
        caller = store.callers[rec["caller_id"]]
        if (
            caller["preferred_language"] not in counselor["languages"]
            and rec["interpretation_status"] != "CONNECTED"
        ):
            raise_err(ERR_LANGUAGE_UNSUPPORTED,
                      "counselor does not cover the caller's language and no interpreter is connected")
        if script is None:
            raise_err(ERR_SCRIPT_NOT_PUBLISHED, "no PUBLISHED script exists for this pair")
        t = now()
        rec["actual_start_at"] = t
        rec["queue_wait_seconds"] = int((t - rec["created_at"]).total_seconds())
        rec["pinned_script_id"] = script["id"]
        rec["session_status"] = "ACTIVE"
        bump(rec)
        return ok_object(session_out(rec))

    if to_status in ("WRAPPED_UP", "DROPPED"):
        if current != "ACTIVE":
            invalid_state("session transition %s -> %s is not allowed" % (current, to_status))
        rec["actual_end_at"] = now()
        rec["session_status"] = to_status
        bump(rec)
        return ok_object(session_out(rec))

    if to_status == "ABANDONED":
        if current not in ("QUEUED", "ASSIGNED"):
            invalid_state("session transition %s -> ABANDONED is not allowed" % current)
        rec["session_status"] = "ABANDONED"
        bump(rec)
        return ok_object(session_out(rec))

    invalid_state("session transition %s -> %s is not allowed" % (current, to_status))


@bp.route("/hotline/sessions/<sid>/interpretation", methods=["POST"])
def transition_interpretation(sid):
    role, uid = require_roles(*SESSION_ROLES)
    rec = store.sessions.get(sid)
    if rec is None:
        not_found("session not found")
    data = get_payload()
    check_unknown(data, {"to_status", "interpreter_id", "scheduled_start_at", "scheduled_end_at"})
    to_status = as_enum(require(data, "to_status"), "to_status", INTERP_STATUSES)
    current = rec["interpretation_status"]

    if to_status == "REQUESTED":
        interpreter_id = data.get("interpreter_id")
        if interpreter_id is None:
            invalid_request("interpreter_id is required for REQUESTED")
        as_str(interpreter_id, "interpreter_id")
        if "scheduled_start_at" not in data or data["scheduled_start_at"] is None:
            invalid_request("scheduled_start_at is required for REQUESTED")
        if "scheduled_end_at" not in data or data["scheduled_end_at"] is None:
            invalid_request("scheduled_end_at is required for REQUESTED")
        start = parse_dt(data["scheduled_start_at"], "scheduled_start_at")
        end = parse_dt(data["scheduled_end_at"], "scheduled_end_at")
        if end <= start:
            invalid_request("scheduled_end_at must be strictly after scheduled_start_at")
        interpreter = store.interpreters.get(interpreter_id)
        if interpreter is None:
            invalid_request("interpreter_id does not reference an existing interpreter")
        if current not in ("NOT_REQUIRED", "FAILED"):
            invalid_state("interpretation transition %s -> REQUESTED is not allowed" % current)
        if rec["session_status"] not in ("QUEUED", "ASSIGNED"):
            invalid_state("interpretation can be requested only while QUEUED or ASSIGNED")
        caller = store.callers[rec["caller_id"]]
        if interpreter["language_code"] != caller["preferred_language"]:
            raise_err(ERR_INTERPRETER_LANGUAGE_MISMATCH,
                      "interpreter language does not match the caller's preferred language")
        if interpreter_window_conflict(interpreter_id, start, end, exclude_session_id=rec["id"]):
            raise_err(ERR_INTERPRETER_OVERLAP,
                      "requested window conflicts with an existing buffered booking")
        if current == "FAILED" and interpreter_id in rec["failed_interpreter_ids"]:
            raise_err(ERR_INTERPRETER_PREVIOUSLY_FAILED,
                      "interpreter previously failed on this session")
        rec["interpreter_id"] = interpreter_id
        rec["scheduled_start_at"] = start
        rec["scheduled_end_at"] = end
        rec["interpretation_status"] = "REQUESTED"
        bump(rec)
        return ok_object(session_out(rec))

    # remaining transitions require a non-terminal session (terminal freezes both)
    if rec["session_status"] in TERMINAL_SESSION:
        invalid_state("terminal session states freeze both status dimensions")

    if to_status == "CONNECTED" and current == "REQUESTED":
        rec["interpretation_status"] = "CONNECTED"
        bump(rec)
        return ok_object(session_out(rec))

    if to_status == "FAILED" and current == "REQUESTED":
        if rec["interpreter_id"] is not None:
            rec["failed_interpreter_ids"].append(rec["interpreter_id"])
        rec["interpreter_id"] = None
        rec["scheduled_start_at"] = None
        rec["scheduled_end_at"] = None
        rec["interpretation_status"] = "FAILED"
        bump(rec)
        return ok_object(session_out(rec))

    if to_status == "NOT_REQUIRED" and current == "FAILED":
        rec["interpretation_status"] = "NOT_REQUIRED"
        bump(rec)
        return ok_object(session_out(rec))

    invalid_state("interpretation transition %s -> %s is not allowed" % (current, to_status))
