"""Referrals: submit, review, initiate evaluation, reject, withdraw."""
from datetime import timedelta

from flask import Blueprint, g, request

from db import db, create_record, now, touch
from errors import (ERR_EVALUATION_ALREADY_OPEN, ERR_INVALID_STATE,
                    ERR_REFERRAL_NOT_PENDING, ERR_REFERRAL_NOT_UNDER_REVIEW,
                    ERR_REFERRAL_NOT_WITHDRAWABLE,
                    ERR_STUDENT_NOT_IN_REFERRED_STATE, raise_err)
from middleware import body, opt_str, req_enum, req_str, require_roles
from response import success
from routes import list_response
from services import (DISABILITY_CATEGORIES, EVALUATION_OPEN_STATES,
                      REFERRAL_REVIEW_WINDOW_DAYS, emit, evaluation_out,
                      get_evaluation, get_referral, get_student, posture_gate,
                      referral_out, school_of_student)

bp = Blueprint("referrals", __name__)

REFERRAL_READERS = ("District504Director", "Section504Coordinator", "SchoolPrincipal", "Teacher")


@bp.post("/referrals")
@require_roles("Teacher", "Section504Coordinator")
def create_referral():
    d = body()
    stu = get_student(req_str(d, "student_id"))
    school = school_of_student(stu)
    posture_gate(school)
    reason = req_str(d, "referral_reason")
    category = req_enum(d, "suspected_disability_category", DISABILITY_CATEGORIES)
    if stu["section_504_status"] != "NONE":
        raise_err(ERR_INVALID_STATE,
                  "Referral is only valid while the student's section_504_status is NONE")
    ts = now()
    rec = create_record(db.referrals, {
        "student_id": stu["id"],
        "submitted_by_staff_id": g.user_id,
        "referral_reason": reason,
        "suspected_disability_category": category,
        "referral_status": "PENDING",
        "submitted_at": ts,
        "review_deadline": ts + timedelta(days=REFERRAL_REVIEW_WINDOW_DAYS),
    })
    stu["section_504_status"] = "REFERRED"
    touch(stu)
    emit("REFERRAL_SUBMITTED", school["id"], rec["id"], g.user_id,
         {"student_id": stu["id"], "suspected_disability_category": category})
    return success(referral_out(rec), 201)


@bp.get("/referrals")
@require_roles(*REFERRAL_READERS)
def list_referrals():
    items = list(db.referrals.values())
    student_id = request.args.get("student_id")
    status = request.args.get("referral_status")
    if student_id is not None:
        items = [r for r in items if r["student_id"] == student_id]
    if status is not None:
        items = [r for r in items if r["referral_status"] == status]
    return list_response(items, referral_out)


@bp.get("/referrals/<referralId>")
@require_roles(*REFERRAL_READERS)
def get_referral_detail(referralId):
    return success(referral_out(get_referral(referralId)), 200)


@bp.post("/referrals/<referralId>/start-review")
@require_roles("Section504Coordinator")
def start_review(referralId):
    ref = get_referral(referralId)
    stu = get_student(ref["student_id"])
    school = school_of_student(stu)
    posture_gate(school)
    if ref["referral_status"] != "PENDING":
        raise_err(ERR_REFERRAL_NOT_PENDING, "Referral must be PENDING to start review")
    if stu["section_504_status"] != "REFERRED":
        raise_err(ERR_STUDENT_NOT_IN_REFERRED_STATE,
                  "Student.section_504_status must be REFERRED")
    ref["referral_status"] = "UNDER_REVIEW"
    touch(ref)
    emit("REFERRAL_REVIEWED", school["id"], ref["id"], g.user_id, {"student_id": stu["id"]})
    return success(referral_out(ref), 200)


@bp.post("/referrals/<referralId>/initiate-evaluation")
@require_roles("Section504Coordinator")
def initiate_evaluation(referralId):
    ref = get_referral(referralId)
    stu = get_student(ref["student_id"])
    school = school_of_student(stu)
    posture_gate(school)
    d = body()
    supersedes = opt_str(d, "supersedes_evaluation_id", None)
    if supersedes is not None:
        get_evaluation(supersedes)  # referenced body id must exist
    if ref["referral_status"] != "UNDER_REVIEW":
        raise_err(ERR_REFERRAL_NOT_UNDER_REVIEW,
                  "Referral must be UNDER_REVIEW to initiate an evaluation")
    for e in db.evaluations.values():
        if e["student_id"] == stu["id"] and e["evaluation_status"] in EVALUATION_OPEN_STATES:
            raise_err(ERR_EVALUATION_ALREADY_OPEN,
                      "Student already has an evaluation in a non-terminal state")
    ev = create_record(db.evaluations, {
        "student_id": stu["id"],
        "referral_id": ref["id"],
        "supersedes_evaluation_id": supersedes,
        "evaluation_status": "INITIATED",
        "parent_consent_obtained_at": None,
        "evaluation_started_at": None,
        "determination_deadline": None,
        "determination_outcome": None,
        "disability_impairment_found": False,
        "major_life_activity_affected": False,
        "determined_by_staff_id": None,
    })
    ref["referral_status"] = "EVALUATION_INITIATED"
    touch(ref)
    stu["section_504_status"] = "EVALUATING"
    touch(stu)
    emit("EVALUATION_INITIATED", school["id"], ev["id"], g.user_id,
         {"student_id": stu["id"], "referral_id": ref["id"],
          "supersedes_evaluation_id": supersedes})
    return success(evaluation_out(ev), 201)


@bp.post("/referrals/<referralId>/reject")
@require_roles("Section504Coordinator")
def reject_referral(referralId):
    ref = get_referral(referralId)
    stu = get_student(ref["student_id"])
    posture_gate(school_of_student(stu))
    if ref["referral_status"] != "UNDER_REVIEW":
        raise_err(ERR_REFERRAL_NOT_UNDER_REVIEW, "Referral must be UNDER_REVIEW to reject")
    ref["referral_status"] = "REJECTED"
    touch(ref)
    stu["section_504_status"] = "NONE"
    touch(stu)
    return success(referral_out(ref), 200)


@bp.post("/referrals/<referralId>/withdraw")
@require_roles("Section504Coordinator")
def withdraw_referral(referralId):
    ref = get_referral(referralId)
    stu = get_student(ref["student_id"])
    posture_gate(school_of_student(stu))
    if ref["referral_status"] not in ("PENDING", "UNDER_REVIEW"):
        raise_err(ERR_REFERRAL_NOT_WITHDRAWABLE,
                  "Referral must be PENDING or UNDER_REVIEW to withdraw")
    ref["referral_status"] = "WITHDRAWN"
    touch(ref)
    stu["section_504_status"] = "NONE"
    touch(stu)
    return success(referral_out(ref), 200)
