"""Permit application endpoints (PRD §3.4)."""
from flask import Blueprint

import clock
import db
import guards
import repo
import response
import tx
import validate as v
from db import db as store
from errors import ApiError
from middleware import ALL_ROLES, require
from services import derive

bp = Blueprint("permits", __name__)


@bp.post("/pre-opening/permit-applications")
@require("LicensingCoordinator", "ProgramDirector")
def create_permit():
    body = v.body()
    program_id = v.req_id(body, "program_id")
    gating_milestone_id = v.req_id(body, "gating_milestone_id")
    permit_type = v.req_enum(body, "permit_type", repo.PERMIT_TYPES)
    review_days = v.req_int(body, "review_days", minimum=1, maximum=180)

    program = repo.get_program(program_id)
    milestone = repo.get_milestone(gating_milestone_id)
    if milestone["program_id"] != program_id:
        raise ApiError("ERR_CROSS_PROGRAM_REFERENCE",
                       "The gating milestone belongs to another program.")
    guards.ensure_not_stabilized(program)
    for existing in repo.permits_of(program_id):
        if existing["permit_type"] == permit_type:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "A %s application already exists for this program." % permit_type)

    ts = db.stamp()
    permit = {
        "id": db.new_id(),
        "program_id": program_id,
        "gating_milestone_id": gating_milestone_id,
        "permit_type": permit_type,
        "is_mandatory": permit_type in repo.MANDATORY_PERMIT_TYPES,
        "review_days": review_days,
        "state": "DRAFT",
        "submitted_at": None,
        "issued_at": None,
        "resubmission_count": 0,
        "deficiency_reason": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    store.permits[permit["id"]] = permit
    tx.commit()
    return response.created(repo.serialize(permit))


@bp.get("/pre-opening/permit-applications")
@require(*ALL_ROLES)
def list_permits():
    program_id = v.q_str("program_id")
    gating_milestone_id = v.q_str("gating_milestone_id")
    permit_type = v.q_enum("permit_type", repo.PERMIT_TYPES)
    state = v.q_enum("state", repo.PERMIT_STATES)
    items = db.sort_created(list(store.permits.values()))
    if program_id:
        items = [p for p in items if p["program_id"] == program_id]
    if gating_milestone_id:
        items = [p for p in items if p["gating_milestone_id"] == gating_milestone_id]
    if permit_type:
        items = [p for p in items if p["permit_type"] == permit_type]
    if state:
        items = [p for p in items if p["state"] == state]
    page, meta = v.paginate(items)
    return response.ok_list(repo.serialize_many(page), meta)


@bp.get("/pre-opening/permit-applications/<permit_id>")
@require(*ALL_ROLES)
def read_permit(permit_id):
    return response.ok(repo.serialize(repo.get_permit(permit_id)))


@bp.post("/pre-opening/permit-applications/<permit_id>/submit")
@require("LicensingCoordinator")
def submit_permit(permit_id):
    permit = repo.get_permit(permit_id)
    program = repo.get_program(permit["program_id"])
    guards.ensure_not_stabilized(program)
    if permit["state"] not in ("DRAFT", "DEFICIENT"):
        raise ApiError("ERR_INVALID_PERMIT_STATE",
                       "An application in state %s may not be submitted." % permit["state"])
    resubmission = permit["state"] == "DEFICIENT"

    milestone = store.milestones.get(permit["gating_milestone_id"])
    allowed = ("COMPLETE", "BLOCKED", "IN_PROGRESS") if resubmission else ("COMPLETE",)
    if milestone is None or milestone["state"] not in allowed:
        raise ApiError("ERR_GATING_MILESTONE_NOT_COMPLETE")
    issued = {p["permit_type"] for p in repo.permits_of(program["id"]) if p["state"] == "ISSUED"}
    for prerequisite in repo.PERMIT_PREREQUISITES[permit["permit_type"]]:
        if prerequisite not in issued:
            raise ApiError("ERR_PERMIT_PREREQUISITE_NOT_MET")

    permit["state"] = "SUBMITTED"
    permit["submitted_at"] = clock.fmt_instant(clock.now())
    if resubmission:
        permit["resubmission_count"] = permit["resubmission_count"] + 1
        permit["deficiency_reason"] = None
        if milestone["state"] == "BLOCKED":
            milestone["state"] = "IN_PROGRESS"
    elif permit["is_mandatory"] and program["schedule_state"] == "CONSTRUCTION_COMPLETE":
        program["schedule_state"] = "LICENSING"

    derive.refresh(program, run_schedule=resubmission and bool(repo.milestones_of(program["id"])))
    tx.commit()
    return response.ok(repo.serialize(permit))


@bp.post("/pre-opening/permit-applications/<permit_id>/record-review")
@require("LicensingCoordinator")
def record_review(permit_id):
    body = v.body()
    decision = v.req_enum(body, "decision", ("ISSUE", "DEFICIENCY"))
    deficiency_reason = v.opt_str(body, "deficiency_reason", 1, 500)

    permit = repo.get_permit(permit_id)
    program = repo.get_program(permit["program_id"])
    guards.ensure_not_stabilized(program)
    if permit["state"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_PERMIT_STATE",
                       "A review may only be recorded against a SUBMITTED application.")

    if decision == "ISSUE":
        permit["state"] = "ISSUED"
        permit["issued_at"] = clock.fmt_instant(clock.now())
        derive.refresh(program)
        tx.commit()
        return response.ok(repo.serialize(permit))

    # --- the five-link deficiency cascade (PRD §3.4) ------------------------
    permit["deficiency_reason"] = deficiency_reason
    permit["state"] = "DEFICIENT"

    milestone = store.milestones.get(permit["gating_milestone_id"])
    if milestone is not None:
        milestone["blocked_days_accrued"] = (
            milestone["blocked_days_accrued"] + permit["review_days"])
        if milestone["state"] in ("IN_PROGRESS", "COMPLETE"):
            milestone["state"] = "BLOCKED"

    derive.refresh(program, run_schedule=bool(repo.milestones_of(program["id"])))
    tx.commit()
    return response.ok(repo.serialize(permit))
