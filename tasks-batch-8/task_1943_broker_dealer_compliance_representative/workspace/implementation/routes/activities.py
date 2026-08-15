"""OutsideActivityRequest endpoints (PRD 3.4): OBA/PST approval pipeline."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_ACTIVITY_NOT_PENDING_DECISION,
    ERR_FORBIDDEN_ROLE,
    ERR_NO_ACTIVE_HEIGHTENED_PLAN,
    ERR_NOT_FOUND,
    ERR_PST_COMP_DETAILS_REQUIRED,
    ERR_REP_NOT_ACTIVE,
    ERR_SD_REP_REQUIRES_HEIGHTENED_PLAN,
    ERR_VALIDATION,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public, touch
from util import round_half_up_int
from validate import (
    get_body, opt_int, opt_str, req_bool, req_date, req_enum, req_str,
    req_str_list, require_path_resource, soft_int,
)

bp = Blueprint("activities", __name__)

ACTIVITY_TYPES = ("OUTSIDE_BUSINESS_ACTIVITY", "PRIVATE_SECURITIES_TRANSACTION")
DECISIONS = ("APPROVE", "APPROVE_WITH_CONDITIONS", "REJECT")
WITHDRAWABLE = ("SUBMITTED", "SUSPENDED_REVIEW", "APPROVED", "APPROVED_WITH_CONDITIONS")
APPROVED_STATES = ("APPROVED", "APPROVED_WITH_CONDITIONS")

# 2.5% supervisory fee = comp / 40, rounded half-up per approval before summation
PST_FEE_NUMER = 1
PST_FEE_DENOM = 40


def _has_active_plan(rep_id):
    return any(p["rep_id"] == rep_id and p["status"] == "ACTIVE"
               for p in db["supervision_plans"].values())


def _compensate_approval(act):
    """Reverse the approval's count and fee accrual (null-safe)."""
    rep = db["representatives"].get(act["rep_id"])
    if rep is None:
        return
    rep["active_approved_activity_count"] -= 1
    rep["pst_fee_total_cents"] -= act.get("supervisory_fee_cents") or 0
    touch(rep)


@bp.post("/outside-activities")
def create_activity():
    caller = authorized(["RegisteredRep"])
    body = get_body()
    # Entity-backed identity (PRD 2.1): rep_id is the caller's X-User-ID, never a
    # payload field. The referenced representative must resolve (priority 3).
    rep = db["representatives"].get(caller.user_id)
    if rep is None:
        raise_error(ERR_NOT_FOUND, "X-User-ID does not resolve to a representative")
    # Priority 5 gate: only ACTIVE reps may submit
    if rep["status"] != "ACTIVE":
        raise_error(ERR_REP_NOT_ACTIVE, "a TERMINATED representative cannot submit requests")
    # Priority 8: schema
    activity_type = req_enum(body, "activity_type", ACTIVITY_TYPES)
    description = req_str(body, "description")
    compensation_expected = req_bool(body, "compensation_expected")
    estimated_comp = opt_int(body, "estimated_gross_comp_cents", non_negative=True)
    start_date = req_date(body, "start_date")

    rec = new_record("outside_activities", {
        "rep_id": rep["id"],
        "activity_type": activity_type,
        "description": description,
        "compensation_expected": compensation_expected,
        "estimated_gross_comp_cents": estimated_comp,
        "start_date": start_date,
        "conditions": None,
        "supervisory_fee_cents": None,
        "decided_by": None,
        "status": "SUBMITTED",
    })
    return success_object(public(rec), status=201)


@bp.get("/outside-activities")
def list_activities():
    return list_response("outside_activities", filters={
        "rep_id": request.args.get("rep_id"),
        "activity_type": request.args.get("activity_type"),
        "status": request.args.get("status"),
    })


@bp.get("/outside-activities/<rid>")
def get_activity(rid):
    return get_one("outside_activities", rid)


@bp.post("/outside-activities/<rid>/decide")
def decide_activity(rid):
    caller = authorized(["CompliancePrincipal"])
    act = require_path_resource("outside_activities", rid)
    # Priority 4: state gate (beats the business-safety gates)
    if act["status"] != "SUBMITTED":
        raise_error(ERR_ACTIVITY_NOT_PENDING_DECISION,
                    "decide is allowed only from SUBMITTED")
    body = get_body()
    decision_raw = body.get("decision")

    rep = db["representatives"].get(act["rep_id"])
    if decision_raw in ("APPROVE", "APPROVE_WITH_CONDITIONS"):
        # Priority 5 gates, in the pinned order: rep ACTIVE -> SD plan -> PST details
        if rep is None or rep["status"] != "ACTIVE":
            raise_error(ERR_REP_NOT_ACTIVE,
                        "decision requires an ACTIVE representative")
        if rep["is_statutorily_disqualified"] and not _has_active_plan(rep["id"]):
            raise_error(ERR_SD_REP_REQUIRES_HEIGHTENED_PLAN,
                        "approval for a statutorily disqualified rep requires an ACTIVE "
                        "heightened supervision plan")
        if (act["activity_type"] == "PRIVATE_SECURITIES_TRANSACTION"
                and act["compensation_expected"]):
            comp = act.get("estimated_gross_comp_cents")
            if not soft_int(comp) or comp <= 0:
                raise_error(ERR_PST_COMP_DETAILS_REQUIRED,
                            "compensated PST approval requires estimated_gross_comp_cents > 0")

    # Priority 8: schema (decision enum; conditions shape)
    decision = req_enum(body, "decision", DECISIONS)
    conditions = None
    if decision == "APPROVE_WITH_CONDITIONS":
        conditions = req_str_list(body, "conditions", non_empty=True)

    if decision in ("APPROVE", "APPROVE_WITH_CONDITIONS"):
        act["decided_by"] = caller.user_id
        act["status"] = ("APPROVED" if decision == "APPROVE"
                         else "APPROVED_WITH_CONDITIONS")
        if decision == "APPROVE_WITH_CONDITIONS":
            act["conditions"] = conditions
        rep["active_approved_activity_count"] += 1
        if (act["activity_type"] == "PRIVATE_SECURITIES_TRANSACTION"
                and act["compensation_expected"]):
            fee = round_half_up_int(act["estimated_gross_comp_cents"] * PST_FEE_NUMER,
                                    PST_FEE_DENOM)
            act["supervisory_fee_cents"] = fee
            rep["pst_fee_total_cents"] += fee
        touch(rep)
    else:  # REJECT requires only the SUBMITTED state
        act["decided_by"] = caller.user_id
        act["status"] = "REJECTED"
    touch(act)
    return success_object(public(act))


@bp.post("/outside-activities/<rid>/withdraw")
def withdraw_activity(rid):
    caller = authorized(["RegisteredRep"])
    act = require_path_resource("outside_activities", rid)
    # Entity-backed ownership: only the owning rep may withdraw
    if caller.user_id != act["rep_id"]:
        raise_error(ERR_FORBIDDEN_ROLE, "only the owning representative may withdraw")
    if act["status"] not in WITHDRAWABLE:
        raise_error(ERR_ACTIVITY_NOT_PENDING_DECISION,
                    "withdraw is allowed only from SUBMITTED, SUSPENDED_REVIEW, "
                    "APPROVED, or APPROVED_WITH_CONDITIONS")
    prior = act["status"]
    act["status"] = "WITHDRAWN"
    touch(act)
    if prior in APPROVED_STATES:
        _compensate_approval(act)
    return success_object(public(act))


@bp.post("/outside-activities/<rid>/revoke")
def revoke_activity(rid):
    authorized(["CompliancePrincipal"])
    act = require_path_resource("outside_activities", rid)
    if act["status"] not in APPROVED_STATES:
        raise_error(ERR_ACTIVITY_NOT_PENDING_DECISION,
                    "revoke is allowed only from APPROVED or APPROVED_WITH_CONDITIONS")
    body = get_body()
    req_str(body, "reason")
    act["status"] = "REVOKED"
    touch(act)
    _compensate_approval(act)
    return success_object(public(act))


@bp.post("/outside-activities/<rid>/resume")
def resume_activity(rid):
    authorized(["CompliancePrincipal"])
    act = require_path_resource("outside_activities", rid)
    if act["status"] != "SUSPENDED_REVIEW":
        raise_error(ERR_ACTIVITY_NOT_PENDING_DECISION,
                    "resume is allowed only from SUSPENDED_REVIEW")
    if not _has_active_plan(act["rep_id"]):
        raise_error(ERR_NO_ACTIVE_HEIGHTENED_PLAN,
                    "resume requires an ACTIVE heightened supervision plan for the rep")
    act["status"] = "SUBMITTED"
    touch(act)
    return success_object(public(act))
