"""Eligibility evaluations: consent flow, start, determination."""
from datetime import timedelta

from flask import Blueprint, g, request

from db import db, create_record, now, touch
from errors import (ERR_DETERMINATION_DEADLINE_MISSED,
                    ERR_EVALUATION_NOT_AWAITING_CONSENT,
                    ERR_EVALUATION_NOT_IN_PROGRESS,
                    ERR_EVALUATION_NOT_INITIATED,
                    ERR_EVALUATION_NOT_READY_TO_START, ERR_PRIOR_EVALUATION_OPEN,
                    ERR_SEGREGATION_OF_DUTIES, raise_err)
from middleware import body, opt_bool, req_bool, req_enum, req_str, require_roles
from response import success
from routes import list_response
from services import (DETERMINATION_OUTCOMES, DETERMINATION_WINDOW_DAYS, emit,
                      evaluation_out, consent_out, get_evaluation, get_student,
                      posture_gate, school_of_evaluation)
from util import days_between

bp = Blueprint("evaluations", __name__)

EVAL_READERS = ("District504Director", "Section504Coordinator", "SchoolPrincipal", "Teacher")


@bp.get("/evaluations")
@require_roles(*EVAL_READERS)
def list_evaluations():
    items = list(db.evaluations.values())
    student_id = request.args.get("student_id")
    referral_id = request.args.get("referral_id")
    supersedes = request.args.get("supersedes_evaluation_id")
    status = request.args.get("evaluation_status")
    if student_id is not None:
        items = [e for e in items if e["student_id"] == student_id]
    if referral_id is not None:
        items = [e for e in items if e["referral_id"] == referral_id]
    if supersedes is not None:
        items = [e for e in items if e.get("supersedes_evaluation_id") == supersedes]
    if status is not None:
        items = [e for e in items if e["evaluation_status"] == status]
    return list_response(items, evaluation_out)


@bp.get("/evaluations/<evaluationId>")
@require_roles(*EVAL_READERS)
def get_evaluation_detail(evaluationId):
    return success(evaluation_out(get_evaluation(evaluationId)), 200)


def _linked_request_consent(evaluation_id):
    """The workflow-created REQUESTED consent record tied to this evaluation."""
    cands = [c for c in db.consents.values()
             if c.get("evaluation_id") == evaluation_id and c["consent_status"] == "REQUESTED"]
    if not cands:
        return None
    return max(cands, key=lambda c: c["_seq"])


@bp.post("/evaluations/<evaluationId>/request-consent")
@require_roles("Section504Coordinator")
def request_consent(evaluationId):
    ev = get_evaluation(evaluationId)
    school = school_of_evaluation(ev)
    posture_gate(school)
    if ev["evaluation_status"] != "INITIATED":
        raise_err(ERR_EVALUATION_NOT_INITIATED, "Evaluation must be INITIATED")
    ev["evaluation_status"] = "CONSENT_PENDING"
    touch(ev)
    scope = "RE_EVALUATION" if ev.get("supersedes_evaluation_id") else "INITIAL_PLAN"
    rec = create_record(db.consents, {
        "student_id": ev["student_id"],
        "evaluation_id": ev["id"],
        "plan_id": None,
        "consent_scope": scope,
        "consent_status": "REQUESTED",
        "requested_at": now(),
        "responded_at": None,
        "responded_by_parent_ref": None,
    })
    return success(consent_out(rec), 201)


@bp.post("/evaluations/<evaluationId>/record-consent")
@require_roles("Section504Coordinator")
def record_consent(evaluationId):
    ev = get_evaluation(evaluationId)
    school = school_of_evaluation(ev)
    posture_gate(school)
    d = body()
    granted = req_bool(d, "granted")
    parent_ref = req_str(d, "responded_by_parent_ref")
    if ev["evaluation_status"] != "CONSENT_PENDING":
        raise_err(ERR_EVALUATION_NOT_AWAITING_CONSENT,
                  "Evaluation must be CONSENT_PENDING to record consent")
    stu = get_student(ev["student_id"])
    rec = _linked_request_consent(ev["id"])
    if rec is not None:
        rec["consent_status"] = "GRANTED" if granted else "DENIED"
        rec["responded_at"] = now()
        rec["responded_by_parent_ref"] = parent_ref
        touch(rec)
    if granted:
        ev["evaluation_status"] = "CONSENT_RECEIVED"
        ev["parent_consent_obtained_at"] = now()
        touch(ev)
        emit("CONSENT_GRANTED", school["id"], ev["id"], g.user_id,
             {"student_id": stu["id"], "consent_id": rec["id"] if rec else None})
    else:
        ev["evaluation_status"] = "CANCELLED"
        touch(ev)
        stu["section_504_status"] = "NONE"
        touch(stu)
        emit("CONSENT_DENIED", school["id"], ev["id"], g.user_id,
             {"student_id": stu["id"], "consent_id": rec["id"] if rec else None})
    return success(evaluation_out(ev), 200)


@bp.post("/evaluations/<evaluationId>/start")
@require_roles("Section504Coordinator")
def start_evaluation(evaluationId):
    ev = get_evaluation(evaluationId)
    posture_gate(school_of_evaluation(ev))
    if ev["evaluation_status"] != "CONSENT_RECEIVED":
        raise_err(ERR_EVALUATION_NOT_READY_TO_START,
                  "Evaluation must be CONSENT_RECEIVED to start")
    ev["evaluation_started_at"] = now()
    ev["determination_deadline"] = now() + timedelta(days=DETERMINATION_WINDOW_DAYS)
    ev["evaluation_status"] = "EVALUATION_IN_PROGRESS"
    touch(ev)
    return success(evaluation_out(ev), 200)


@bp.post("/evaluations/<evaluationId>/determine")
@require_roles("Section504Coordinator")
def determine(evaluationId):
    ev = get_evaluation(evaluationId)
    school = school_of_evaluation(ev)
    posture_gate(school)
    d = body()
    outcome = req_enum(d, "determination_outcome", DETERMINATION_OUTCOMES)
    impairment = opt_bool(d, "disability_impairment_found", False)
    mla = opt_bool(d, "major_life_activity_affected", False)
    # State preconditions (priority 6)
    if ev["evaluation_status"] != "EVALUATION_IN_PROGRESS":
        raise_err(ERR_EVALUATION_NOT_IN_PROGRESS,
                  "Evaluation must be EVALUATION_IN_PROGRESS to determine")
    if ev.get("supersedes_evaluation_id"):
        prior = db.evaluations.get(ev["supersedes_evaluation_id"])
        if prior is None or prior["evaluation_status"] != "DETERMINATION_MADE":
            raise_err(ERR_PRIOR_EVALUATION_OPEN,
                      "Superseded evaluation must be in DETERMINATION_MADE first")
    # Segregation of duties (priority 8): determiner != referral submitter
    referral = db.referrals.get(ev["referral_id"])
    if referral is not None and referral.get("submitted_by_staff_id") == g.user_id:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "The determining staff member must differ from the referral submitter")
    # Determination deadline (priority 10): whole days from evaluation_started_at
    days_elapsed = days_between(now(), ev["evaluation_started_at"])
    is_late = days_elapsed > DETERMINATION_WINDOW_DAYS
    if is_late and outcome == "NOT_ELIGIBLE":
        raise_err(ERR_DETERMINATION_DEADLINE_MISSED,
                  "A NOT_ELIGIBLE determination after the 60-day window is forbidden")
    stu = get_student(ev["student_id"])
    ev["determination_outcome"] = outcome
    ev["disability_impairment_found"] = impairment
    ev["major_life_activity_affected"] = mla
    ev["determined_by_staff_id"] = g.user_id
    ev["evaluation_status"] = "DETERMINATION_MADE"
    touch(ev)
    if outcome == "NOT_ELIGIBLE":
        stu["section_504_status"] = "NOT_ELIGIBLE"
        touch(stu)
    else:
        # ELIGIBLE leaves the student EVALUATING; a re-evaluation chain switches
        # the plan's evaluation link once the new evaluation is determined ELIGIBLE.
        supersedes = ev.get("supersedes_evaluation_id")
        if supersedes:
            for plan in db.plans.values():
                if plan["evaluation_id"] == supersedes:
                    plan["evaluation_id"] = ev["id"]
                    touch(plan)
    if is_late and outcome == "ELIGIBLE":
        emit("REVIEW_COMPLETED_LATE", school["id"], ev["id"], g.user_id,
             {"kind": "LATE_ELIGIBLE_DETERMINATION", "days_elapsed": days_elapsed})
    emit("DETERMINATION_MADE", school["id"], ev["id"], g.user_id,
         {"student_id": stu["id"], "determination_outcome": outcome})
    return success(evaluation_out(ev), 200)
