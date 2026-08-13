"""Candidates: registration, read, withdraw cascade (PRD §3.5)."""
import db
import serializers
import util
from errors import api_err, err_not_found, err_ownership
from flask import Blueprint
from middleware import authenticate, require_roles
from response import success_object
from services import core
from util import bump, new_id, next_seq, req_enum, req_string

bp = Blueprint("candidates", __name__)

GROUP_CODES = ["GROUP_A", "GROUP_B", "GROUP_C", "GROUP_D", "UNDISCLOSED"]
READ_ROLES = ["HiringManager", "TalentAssessmentAdmin", "ComplianceOfficer",
              "DecisionOfficer", "Candidate"]


@bp.post("/talent/candidates")
def create_candidate():
    ctx = authenticate()
    require_roles(ctx, ["HiringManager", "TalentAssessmentAdmin"])
    body = util.get_body()
    external_ref = req_string(body, "external_ref")
    full_name = req_string(body, "full_name")
    email = req_string(body, "email")
    group_code = req_enum(body, "group_code", GROUP_CODES)
    for c in db.stores["candidates"].values():
        if c["external_ref"] == external_ref:
            raise api_err("ERR_DUPLICATE_CANDIDATE_REF", "external_ref already exists")
    now = db.get_now()
    rec = {
        "id": new_id(),
        "external_ref": external_ref,
        "full_name": full_name,
        "email": email,
        "group_code": group_code,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_created": now,
        "_seq": next_seq(),
    }
    db.stores["candidates"][rec["id"]] = rec
    return success_object(serializers.candidate(rec), 201)


@bp.get("/talent/candidates/<cid>")
def get_candidate(cid):
    ctx = authenticate()
    require_roles(ctx, READ_ROLES)
    c = db.stores["candidates"].get(cid)
    if c is None:
        raise err_not_found("Candidate not found")
    if ctx.role == "Candidate" and ctx.user_id != c["id"]:
        raise err_ownership("Candidate may only read own record")
    return success_object(serializers.candidate(c))


@bp.post("/talent/candidates/<cid>/withdraw")
def withdraw_candidate(cid):
    ctx = authenticate()
    require_roles(ctx, ["Candidate", "HiringManager"])
    c = db.stores["candidates"].get(cid)
    if c is None:
        raise err_not_found("Candidate not found")
    if ctx.role == "Candidate" and ctx.user_id != c["id"]:
        raise err_ownership("Candidate may only withdraw self")
    if c["status"] != "ACTIVE":
        raise api_err("ERR_CANDIDATE_WITHDRAWN", "Candidate is already WITHDRAWN")
    c["status"] = "WITHDRAWN"
    bump(c)
    # Cascade: cancel non-terminal assessments (which also cancels that
    # candidate's SCHEDULED sessions in the same cycle and withdraws PENDING
    # accommodations), then cancel any remaining SCHEDULED sessions anywhere.
    for a in list(db.stores["assessments"].values()):
        if a["candidate_id"] == cid and a["admin_status"] in core.CANCELLABLE_ADMIN:
            core.cancel_assessment(a, "CANDIDATE_WITHDRAWN")
    for s in db.stores["sessions"].values():
        if s["candidate_id"] == cid and s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            s["cancellation_reason"] = "CANDIDATE_WITHDRAWN"
            bump(s)
            core.recompute_interviewer_minutes(s["interviewer_id"])
            iv = db.stores["interviewers"].get(s["interviewer_id"])
            if iv is not None:
                bump(iv)
    return success_object(serializers.candidate(c))
