"""Curriculum plan endpoints."""
from flask import Blueprint

import db
from errors import raise_err
from middleware import route, ALL_ROLES
from response import success_object
from serializers import ser_curriculum_plan
from services import core
from validation import (
    get_body, req_enum, opt_string, req_subject_list, req_int,
    check_core_subjects, PLAN_REVIEW_DECISIONS,
)

bp = Blueprint("plans", __name__)

_CHAIN = (("curriculum_plan", "plan_id", db.curriculum_plans),)


def _plan_family_id(plan):
    en = core.enrollment_of_plan(plan)
    st = core.student_of_enrollment(en) if en else None
    return st["family_id"] if st else None


@bp.route("/enrollments/<enrollment_id>/curriculum-plans", methods=["POST"])
@route(["Parent"], ownership=("enrollment", "enrollment_id"),
       parent_chain=(("enrollment", "enrollment_id", db.enrollments),))
def create_plan(enrollment_id):
    body = get_body()
    subjects = req_subject_list(body, "subjects")
    for p in db.curriculum_plans.values():
        if p["enrollment_id"] == enrollment_id:
            raise_err("ERR_PLAN_ALREADY_EXISTS", "Enrollment already has a curriculum plan")
    rec = core.make_record({
        "enrollment_id": enrollment_id,
        "subjects": list(subjects),
        "status": "DRAFT",
        "revision_count": 0,
        "reviewer_id": None,
        "review_notes": None,
    })
    db.curriculum_plans[rec["id"]] = rec
    return success_object(ser_curriculum_plan(rec), status=201)


@bp.route("/curriculum-plans/<plan_id>", methods=["GET"])
@route(ALL_ROLES, ownership=("curriculum_plan", "plan_id"), parent_chain=_CHAIN)
def get_plan(plan_id):
    return success_object(ser_curriculum_plan(db.curriculum_plans[plan_id]))


@bp.route("/curriculum-plans/<plan_id>/submit", methods=["POST"])
@route(["Parent"], ownership=("curriculum_plan", "plan_id"), parent_chain=_CHAIN)
def submit_plan(plan_id):
    plan = db.curriculum_plans[plan_id]
    if plan["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only DRAFT or REVISION_REQUESTED plans may be submitted")
    check_core_subjects(plan["subjects"])
    if plan["status"] == "REVISION_REQUESTED":
        plan["revision_count"] += 1
    plan["status"] = "SUBMITTED"
    core.touch(plan)
    return success_object(ser_curriculum_plan(plan))


@bp.route("/curriculum-plans/<plan_id>/review", methods=["POST"])
@route(["Reviewer"], parent_chain=_CHAIN)
def review_plan(plan_id):
    from flask import request as freq
    plan = db.curriculum_plans[plan_id]
    body = get_body()
    decision = req_enum(body, "decision", PLAN_REVIEW_DECISIONS)
    notes = opt_string(body, "notes")
    if plan["status"] not in ("SUBMITTED", "AMENDMENT_REVIEW"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only SUBMITTED or AMENDMENT_REVIEW plans may be reviewed")
    # reviewer conflict of interest: reviewer must not be the student's parent
    if freq.user_id == _plan_family_id(plan):
        raise_err("ERR_REVIEWER_CONFLICT_OF_INTEREST",
                  "A parent may not review their own child's plan")
    plan["reviewer_id"] = freq.user_id
    plan["review_notes"] = notes
    plan["status"] = "APPROVED" if decision == "APPROVE" else "REVISION_REQUESTED"
    core.touch(plan)
    return success_object(ser_curriculum_plan(plan))


@bp.route("/curriculum-plans/<plan_id>/amend", methods=["POST"])
@route(["Parent"], ownership=("curriculum_plan", "plan_id"), parent_chain=_CHAIN)
def amend_plan(plan_id):
    plan = db.curriculum_plans[plan_id]
    body = get_body()
    subjects = req_subject_list(body, "subjects")
    expected = req_int(body, "expected_curriculum_plan_version", lo=0)
    if plan["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only APPROVED plans may be amended")
    if expected != plan["version"]:
        raise_err("ERR_STALE_VERSION",
                  "expected_curriculum_plan_version does not match current version")
    check_core_subjects(subjects)
    plan["subjects"] = list(subjects)
    plan["status"] = "AMENDMENT_REVIEW"
    core.touch(plan)
    return success_object(ser_curriculum_plan(plan))
