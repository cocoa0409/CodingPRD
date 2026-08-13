"""Review events: schedule, start, complete (four outcome cascades), cancel."""
from datetime import timedelta

from flask import Blueprint, g, request

from db import db, create_record, now, touch
from errors import (ERR_IEP_NOT_ACTIVE, ERR_PARENT_CONSENT_REQUIRED,
                    ERR_PLAN_NOT_ACTIVE, ERR_PLAN_NOT_UNDER_REVIEW,
                    ERR_REVIEW_ALREADY_SCHEDULED, ERR_REVIEW_NOT_IN_PROGRESS,
                    ERR_REVIEW_NOT_SCHEDULED, raise_err)
from middleware import body, req_enum, req_str, require_roles
from response import success
from routes import list_response
from services import (ANNUAL_WINDOW_DAYS, RE_EVAL_WINDOW_DAYS, REVIEW_OUTCOMES,
                      REVIEW_TYPES, annual_review_grace_delta, emit, get_plan,
                      get_review, get_student, posture_gate, recompute_posture,
                      review_out, school_of_plan)
from util import parse_dt

bp = Blueprint("reviews", __name__)

REVIEW_READERS = ("District504Director", "Section504Coordinator", "SchoolPrincipal", "Teacher", "Parent")


@bp.post("/reviews")
@require_roles("Section504Coordinator", "District504Director")
def create_review():
    d = body()
    plan = get_plan(req_str(d, "plan_id"))
    school = school_of_plan(plan)
    posture_gate(school)
    review_type = req_enum(d, "review_type", REVIEW_TYPES)
    scheduled_for = parse_dt(req_str(d, "scheduled_for"), "scheduled_for")
    if plan["plan_status"] != "ACTIVE":
        raise_err(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE to schedule a review")
    for rv in db.reviews.values():
        if rv["plan_id"] == plan["id"] and rv["review_status"] in ("SCHEDULED", "IN_PROGRESS"):
            raise_err(ERR_REVIEW_ALREADY_SCHEDULED,
                      "Plan already has a review in SCHEDULED or IN_PROGRESS")
    rec = create_record(db.reviews, {
        "plan_id": plan["id"],
        "review_type": review_type,
        "review_status": "SCHEDULED",
        "scheduled_for": scheduled_for,
        "completed_at": None,
        "outcome": None,
        "was_late": False,
    })
    plan["plan_status"] = "UNDER_ANNUAL_REVIEW"
    touch(plan)
    return success(review_out(rec), 201)


@bp.get("/reviews")
@require_roles(*REVIEW_READERS)
def list_reviews():
    items = list(db.reviews.values())
    plan_id = request.args.get("plan_id")
    status = request.args.get("review_status")
    rtype = request.args.get("review_type")
    if plan_id is not None:
        items = [r for r in items if r["plan_id"] == plan_id]
    if status is not None:
        items = [r for r in items if r["review_status"] == status]
    if rtype is not None:
        items = [r for r in items if r["review_type"] == rtype]
    return list_response(items, review_out)


@bp.get("/reviews/<reviewId>")
@require_roles(*REVIEW_READERS)
def get_review_detail(reviewId):
    return success(review_out(get_review(reviewId)), 200)


@bp.post("/reviews/<reviewId>/start")
@require_roles("Section504Coordinator")
def start_review(reviewId):
    rv = get_review(reviewId)
    plan = get_plan(rv["plan_id"])
    posture_gate(school_of_plan(plan))
    if rv["review_status"] == "SCHEDULED":
        if plan["plan_status"] != "UNDER_ANNUAL_REVIEW":
            raise_err(ERR_PLAN_NOT_UNDER_REVIEW,
                      "Plan must be UNDER_ANNUAL_REVIEW to start the review")
    elif rv["review_status"] == "OVERDUE":
        pass
    else:
        raise_err(ERR_REVIEW_NOT_SCHEDULED,
                  "Review must be SCHEDULED (or OVERDUE) to start")
    rv["review_status"] = "IN_PROGRESS"
    touch(rv)
    return success(review_out(rv), 200)


def _compute_was_late(rv):
    grace = annual_review_grace_delta(rv["review_type"])
    return rv["completed_at"] > rv["scheduled_for"] + grace


def _complete_continue_plan(rv, plan, school):
    plan["plan_status"] = "ACTIVE"
    touch(plan)
    if rv["review_type"] == "ANNUAL":
        plan["next_annual_review_due"] = rv["completed_at"] + timedelta(days=ANNUAL_WINDOW_DAYS)
    elif rv["review_type"] == "RE_EVALUATION":
        plan["next_re_evaluation_due"] = rv["completed_at"] + timedelta(days=RE_EVAL_WINDOW_DAYS)
        # Spawn the re-evaluation: INITIATED, superseding the plan's current evaluation.
        prior = db.evaluations.get(plan["evaluation_id"])
        create_record(db.evaluations, {
            "student_id": plan["student_id"],
            "referral_id": prior["referral_id"] if prior else None,
            "supersedes_evaluation_id": plan["evaluation_id"],
            "evaluation_status": "INITIATED",
            "parent_consent_obtained_at": None,
            "evaluation_started_at": None,
            "determination_deadline": None,
            "determination_outcome": None,
            "disability_impairment_found": False,
            "major_life_activity_affected": False,
            "determined_by_staff_id": None,
        })


def _complete_modify_plan(rv, plan, school):
    # Cyclic revision loop: ACTIVE -> UNDER_ANNUAL_REVIEW -> DRAFT; the student's
    # section_504_status remains PLAN_ACTIVE until the plan exits DRAFT again.
    plan["plan_status"] = "DRAFT"
    touch(plan)


def _check_exit_to_iep_gates(plan):
    """Priority 7 (parent consent) before priority 17 (IEP gate), per PRD section 2.8."""
    stu = get_student(plan["student_id"])
    consent = any(c for c in db.consents.values()
                  if c.get("plan_id") == plan["id"] and c["consent_scope"] == "EXIT_TO_IEP"
                  and c["consent_status"] == "GRANTED")
    if not consent:
        raise_err(ERR_PARENT_CONSENT_REQUIRED,
                  "A GRANTED EXIT_TO_IEP parent consent record is required")
    if stu["iep_status"] != "IEP_ACTIVE":
        raise_err(ERR_IEP_NOT_ACTIVE,
                  "Student.iep_status must be IEP_ACTIVE for EXIT_TO_IEP")


def _apply_exit_to_iep(rv, plan, school):
    stu = get_student(plan["student_id"])
    plan["plan_status"] = "EXITED_TO_IEP"
    touch(plan)
    stu["section_504_status"] = "EXITED_TO_IEP"
    touch(stu)
    for a in db.accommodations.values():
        if a["plan_id"] == plan["id"] and a["accommodation_status"] != "DISCONTINUED":
            a["accommodation_status"] = "DISCONTINUED"
            touch(a)
    for a in db.acks.values():
        if a["plan_id"] == plan["id"] and a["ack_status"] == "PENDING":
            a["ack_status"] = "DECLINED"
            a["ack_responded_at"] = now()
            touch(a)
    for t in db.testing_requests.values():
        if t["plan_id"] == plan["id"] and t["request_status"] in ("SUBMITTED", "PENDING_DISTRICT_REVIEW"):
            t["request_status"] = "DENIED"
            touch(t)


def _complete_terminate(rv, plan, school):
    plan["plan_status"] = "TERMINATED"
    touch(plan)
    stu = get_student(plan["student_id"])
    stu["section_504_status"] = "TERMINATED"
    touch(stu)
    for a in db.accommodations.values():
        if a["plan_id"] == plan["id"] and a["accommodation_status"] != "DISCONTINUED":
            a["accommodation_status"] = "DISCONTINUED"
            touch(a)
    emit("PLAN_TERMINATED", school["id"], plan["id"], g.user_id,
         {"student_id": plan["student_id"]})


@bp.post("/reviews/<reviewId>/complete")
@require_roles("Section504Coordinator")
def complete_review(reviewId):
    rv = get_review(reviewId)
    plan = get_plan(rv["plan_id"])
    school = school_of_plan(plan)
    posture_gate(school)
    d = body()
    outcome = req_enum(d, "outcome", REVIEW_OUTCOMES)
    if rv["review_status"] != "IN_PROGRESS":
        raise_err(ERR_REVIEW_NOT_IN_PROGRESS, "Review must be IN_PROGRESS to complete")
    if plan["plan_status"] != "UNDER_ANNUAL_REVIEW":
        raise_err(ERR_PLAN_NOT_UNDER_REVIEW,
                  "Plan must be UNDER_ANNUAL_REVIEW to complete the review")
    # Outcome gates are evaluated BEFORE any mutation is committed (atomicity).
    if outcome == "EXIT_TO_IEP":
        _check_exit_to_iep_gates(plan)
    rv["completed_at"] = now()
    rv["outcome"] = outcome
    rv["review_status"] = "COMPLETED"
    rv["was_late"] = _compute_was_late(rv)
    touch(rv)
    if rv["was_late"]:
        emit("REVIEW_COMPLETED_LATE", school["id"], rv["id"], g.user_id,
             {"plan_id": plan["id"], "review_type": rv["review_type"]})
    if outcome == "CONTINUE_PLAN":
        _complete_continue_plan(rv, plan, school)
    elif outcome == "MODIFY_PLAN":
        _complete_modify_plan(rv, plan, school)
    elif outcome == "EXIT_TO_IEP":
        _apply_exit_to_iep(rv, plan, school)
    elif outcome == "TERMINATE_504":
        _complete_terminate(rv, plan, school)
    # A completed OVERDUE review leaves the overdue set -> posture may move.
    recompute_posture(school, g.user_id)
    return success(review_out(rv), 200)


@bp.post("/reviews/<reviewId>/cancel")
@require_roles("Section504Coordinator")
def cancel_review(reviewId):
    rv = get_review(reviewId)
    plan = get_plan(rv["plan_id"])
    posture_gate(school_of_plan(plan))
    if rv["review_status"] != "SCHEDULED":
        raise_err(ERR_REVIEW_NOT_SCHEDULED, "Review must be SCHEDULED to cancel")
    rv["review_status"] = "CANCELLED"
    touch(rv)
    # Compensation: plan reverts UNDER_ANNUAL_REVIEW -> ACTIVE.
    if plan["plan_status"] == "UNDER_ANNUAL_REVIEW":
        plan["plan_status"] = "ACTIVE"
        touch(plan)
    return success(review_out(rv), 200)
