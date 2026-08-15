"""RemediationPlan endpoints (PRD 3.9) — draft / submit / review cycle."""

from flask import Blueprint, g

from db import db
from errors import ApiError
from records import new_remediation_plan, touch
from response import ok_object
from routes.common import authenticate, get_or_404, json_body
from serializers import serialize_remediation_plan
from util import Body, PLAN_REVIEW_DECISIONS, ROOT_CAUSE_CODES

bp = Blueprint("plans", __name__)


def _plan_merchant_id(plan):
    en = db.program_enrollments.get(plan["enrollment_id"])
    return en["merchant_id"] if en is not None else None


@bp.post("/acquirer/remediation-plans")
def create_plan():
    authenticate(("MerchantUser",))
    b = Body(json_body())
    enrollment_id = b.req_str("enrollment_id")
    root_cause_codes = b.req_enum_list("root_cause_codes", ROOT_CAUSE_CODES, min_len=1)
    corrective_actions = b.req_str_list("corrective_actions", min_len=1)

    # Priority 3: body-referenced enrollment (+ ownership hiding).
    en = None
    if enrollment_id is not None:
        en = get_or_404(db.program_enrollments, enrollment_id, "ProgramEnrollment")
        if en["merchant_id"] != g.uid:
            raise ApiError(404, "ERR_NOT_FOUND", "Resource not found")
    # Priority 5: enrollment open; at most one DRAFT/SUBMITTED plan per enrollment.
    if en is not None:
        if en["status"] == "EXITED":
            raise ApiError(409, "ERR_INVALID_ENROLLMENT_STATE",
                           "Cannot draft a plan for an EXITED enrollment")
        if any(p for p in db.remediation_plans.values()
               if p["enrollment_id"] == en["id"] and p["status"] in ("DRAFT", "SUBMITTED")):
            raise ApiError(409, "ERR_INVALID_PLAN_STATE",
                           "Another plan of this enrollment is already DRAFT or SUBMITTED")
    # Priority 6: suspension gate.
    if en is not None:
        merchant = db.merchants[en["merchant_id"]]
        if merchant["status"] != "ACTIVE":
            raise ApiError(409, "ERR_MERCHANT_SUSPENDED", "Merchant is SUSPENDED")
    b.raise_pending()

    plan = new_remediation_plan(en["id"], root_cause_codes, corrective_actions)
    db.remediation_plans[plan["id"]] = plan
    return ok_object(serialize_remediation_plan(plan), status=201)


@bp.post("/acquirer/remediation-plans/<pid>/submit")
def submit_plan(pid):
    authenticate(("MerchantUser",))
    plan = get_or_404(db.remediation_plans, pid, "RemediationPlan")
    en = db.program_enrollments[plan["enrollment_id"]]
    if en["merchant_id"] != g.uid:
        raise ApiError(404, "ERR_NOT_FOUND", "Resource not found")
    # Priority 5: DRAFT submits; RETURNED resubmits (review cycle).
    if plan["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError(409, "ERR_INVALID_PLAN_STATE", "Only a DRAFT or RETURNED plan can be submitted")
    # Priority 6: suspension gate.
    merchant = db.merchants[en["merchant_id"]]
    if merchant["status"] != "ACTIVE":
        raise ApiError(409, "ERR_MERCHANT_SUSPENDED", "Merchant is SUSPENDED")
    plan["status"] = "SUBMITTED"
    touch(plan)
    return ok_object(serialize_remediation_plan(plan))


@bp.post("/acquirer/remediation-plans/<pid>/review")
def review_plan(pid):
    authenticate(("RiskOfficer",))
    plan = get_or_404(db.remediation_plans, pid, "RemediationPlan")
    if plan["status"] != "SUBMITTED":
        raise ApiError(409, "ERR_INVALID_PLAN_STATE", "Only a SUBMITTED plan can be reviewed")
    b = Body(json_body())
    decision = b.req_enum("decision", PLAN_REVIEW_DECISIONS)
    decision_note = b.opt_str("decision_note")
    b.raise_pending()

    plan["reviewed_by_user_id"] = g.uid
    plan["decision_note"] = decision_note
    if decision == "APPROVE":
        plan["status"] = "APPROVED"
        en = db.program_enrollments[plan["enrollment_id"]]
        if en["status"] == "ACTIVE":
            en["status"] = "REMEDIATION"  # fines stop while in REMEDIATION
            touch(en)
    else:  # RETURN — the merchant may edit and resubmit
        plan["status"] = "RETURNED"
    touch(plan)
    return ok_object(serialize_remediation_plan(plan))
