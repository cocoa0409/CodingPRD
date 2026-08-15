"""Lockout procedures: authoring, activation / re-activation, retirement (PRD 3.3)."""

from datetime import timedelta

from flask import Blueprint, request

import db
from clock import CLOCK, fmt
from errors import ApiError
from middleware import auth, paginate, ALL_ROLES
from response import ok, ok_list
from services import core

bp = Blueprint("lockout_procedures", __name__)

_STEP_KEYS = ("step_no", "action", "isolation_point")


@bp.route("/lockout-procedures", methods=["POST"])
def create_procedure():
    auth(["EHSManager"])
    body = core.body_json()
    machine_id = core.req_str(body, "machine_id")
    survey_id = core.req_str(body, "survey_id")
    steps = core.req_array(body, "steps", min_len=1, required_keys=_STEP_KEYS)
    m = core.get_or_404("machines", machine_id, "Machine")
    sv = core.get_or_404("energy_surveys", survey_id, "EnergySurvey")
    if sv["machine_id"] != m["id"]:
        # Cross-reference outside the machine scope reports as NOT_FOUND (PRD 2.9).
        raise ApiError("ERR_NOT_FOUND", 404, "Survey belongs to a different machine")
    # Structural rule: at most one procedure in DRAFT or ACTIVE per machine; a
    # single successor DRAFT is allowed only while the current procedure is
    # UNDER_REVISION (i.e. when no DRAFT/ACTIVE row exists).
    for p in db.DB["lockout_procedures"].values():
        if p["machine_id"] == m["id"] and p["status"] in ("DRAFT", "ACTIVE"):
            raise ApiError("ERR_PROCEDURE_CONFLICT", 409,
                           "Machine already has a procedure in DRAFT or ACTIVE status")
    revision_no = 1 + sum(1 for p in db.DB["lockout_procedures"].values()
                          if p["machine_id"] == m["id"])
    proc = core.stamp_new({
        "id": core.new_id(),
        "machine_id": m["id"],
        "survey_id": sv["id"],
        "steps": steps,
        "revision_no": revision_no,
        # Snapshot of the survey's isolation-point count; never re-read later.
        "isolation_point_count": sv["isolation_point_count"],
        "status": "DRAFT",
        "activated_at": None,
        "last_completed_audit_at": None,
        "audit_due_at": None,
    })
    db.DB["lockout_procedures"][proc["id"]] = proc
    return ok(core.procedure_view(proc), 201)


@bp.route("/lockout-procedures", methods=["GET"])
def list_procedures():
    auth(ALL_ROLES)
    machine_id = request.args.get("machine_id")
    survey_id = request.args.get("survey_id")
    status = request.args.get("status")
    items = list(db.DB["lockout_procedures"].values())
    if machine_id is not None:
        items = [p for p in items if p["machine_id"] == machine_id]
    if survey_id is not None:
        items = [p for p in items if p["survey_id"] == survey_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.procedure_view(p) for p in page], total, limit, offset)


@bp.route("/lockout-procedures/<pid>", methods=["GET"])
def get_procedure(pid):
    auth(ALL_ROLES)
    proc = core.get_or_404("lockout_procedures", pid, "LockoutProcedure")
    return ok(core.procedure_view(proc))


@bp.route("/lockout-procedures/<pid>/activate", methods=["POST"])
def activate_procedure(pid):
    auth(["EHSManager"])
    body = core.body_json()
    proc = core.get_or_404("lockout_procedures", pid, "LockoutProcedure")
    if proc["status"] not in ("DRAFT", "UNDER_REVISION"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a DRAFT or UNDER_REVISION procedure can be activated")
    first_activation = proc["status"] == "DRAFT"
    if not first_activation:
        note = body.get("revalidation_note")
        if not isinstance(note, str) or not note.strip():
            raise ApiError("ERR_VALIDATION", 400,
                           "revalidation_note is required to re-activate an UNDER_REVISION procedure")
    sv = db.DB["energy_surveys"].get(proc["survey_id"])
    if sv is None or sv["status"] != "APPROVED":
        raise ApiError("ERR_SURVEY_NOT_APPROVED", 409,
                       "The procedure's energy survey is not APPROVED")
    now = CLOCK.now()
    if first_activation:
        proc["activated_at"] = fmt(now)
        proc["audit_due_at"] = fmt(now + timedelta(days=core.WINDOW_DAYS))
        # A sibling sitting in UNDER_REVISION is automatically superseded.
        for p in db.DB["lockout_procedures"].values():
            if (p["machine_id"] == proc["machine_id"] and p["id"] != proc["id"]
                    and p["status"] == "UNDER_REVISION"):
                p["status"] = "SUPERSEDED"
                core.touch(p)
    # Re-activation leaves activated_at / audit_due_at untouched; both paths
    # flip every still-UNREVIEWED modification of the machine to REVIEWED.
    for mod in db.DB["modifications"].values():
        if mod["machine_id"] == proc["machine_id"] and mod["review_status"] == "UNREVIEWED":
            mod["review_status"] = "REVIEWED"
    proc["status"] = "ACTIVE"
    core.touch(proc)
    return ok(core.procedure_view(proc))


@bp.route("/lockout-procedures/<pid>/retire", methods=["POST"])
def retire_procedure(pid):
    auth(["EHSManager"])
    proc = core.get_or_404("lockout_procedures", pid, "LockoutProcedure")
    if proc["status"] not in ("DRAFT", "ACTIVE", "UNDER_REVISION"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a DRAFT, ACTIVE, or UNDER_REVISION procedure can be retired")
    for s in db.DB["lockout_sessions"].values():
        if s["procedure_id"] == pid and s["status"] in core.OPEN_SESSION_STATUSES:
            raise ApiError("ERR_PROCEDURE_IN_USE", 409,
                           "A session referencing this procedure is still open")
    proc["status"] = "RETIRED"
    core.touch(proc)
    return ok(core.procedure_view(proc))
