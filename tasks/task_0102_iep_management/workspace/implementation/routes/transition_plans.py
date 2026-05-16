"""Transition plan routes."""

from flask import Blueprint

from core.auth import require_role
from core.envelope import success_object
from core.errors import APIError
from core.store import TRANSITION_PLANS, stamp_create, stamp_update
from core.validation import (
    get_district, get_student, get_iep, require_json_body, check_version,
)
from services.serializers import transition_plan_dto


bp = Blueprint("transition_plans", __name__)


def _existing_plan_for_iep(iep_id: str):
    for tp in TRANSITION_PLANS.values():
        if tp.get("iep_id") == iep_id:
            return tp
    return None


@bp.route("/districts/<district_id>/students/<student_id>/ieps/<iep_id>/transition-plan", methods=["POST"])
def create_plan(district_id, student_id, iep_id):
    require_role(["SpecialEducationTeacher"])
    get_district(district_id)
    get_student(district_id, student_id)
    iep = get_iep(district_id, student_id, iep_id)
    body = require_json_body()

    if iep.get("status") not in ("DRAFT", "AMENDMENT_PENDING"):
        raise APIError("ERR_IEP_NOT_AMENDABLE_FOR_TRANSITION",
                       "IEP must be DRAFT or AMENDMENT_PENDING.")
    if _existing_plan_for_iep(iep_id) is not None:
        raise APIError("ERR_INVALID_REQUEST", "TransitionPlan already exists for this IEP.")

    post_secondary_goal = body.get("post_secondary_goal")
    required_courses = body.get("required_courses")
    outside_agency_referrals = body.get("outside_agency_referrals", [])
    parent_invitation_documented = body.get("parent_invitation_documented", False)
    student_invitation_documented = body.get("student_invitation_documented", False)

    if not isinstance(post_secondary_goal, str) or not (10 <= len(post_secondary_goal) <= 1000):
        raise APIError("ERR_INVALID_REQUEST", "post_secondary_goal length must be 10..1000.")
    if not isinstance(required_courses, list) or len(required_courses) == 0:
        raise APIError("ERR_INVALID_REQUEST", "required_courses must be a non-empty array.")
    for c in required_courses:
        if not isinstance(c, dict) or "course_code" not in c or "projected_completion_term" not in c:
            raise APIError("ERR_INVALID_REQUEST",
                           "Each required_courses entry must include course_code and projected_completion_term.")
    if not isinstance(outside_agency_referrals, list):
        raise APIError("ERR_INVALID_REQUEST", "outside_agency_referrals must be an array.")
    for r in outside_agency_referrals:
        if not isinstance(r, dict) or "agency_name" not in r or "contact_role" not in r:
            raise APIError("ERR_INVALID_REQUEST",
                           "Each outside_agency_referrals entry must include agency_name and contact_role.")
    if not isinstance(parent_invitation_documented, bool):
        raise APIError("ERR_INVALID_REQUEST", "parent_invitation_documented must be boolean.")
    if not isinstance(student_invitation_documented, bool):
        raise APIError("ERR_INVALID_REQUEST", "student_invitation_documented must be boolean.")

    plan = {
        "iep_id": iep_id,
        "student_id": student_id,
        "post_secondary_goal": post_secondary_goal,
        "required_courses": list(required_courses),
        "outside_agency_referrals": list(outside_agency_referrals),
        "parent_invitation_documented": parent_invitation_documented,
        "student_invitation_documented": student_invitation_documented,
        "status": "DRAFT",
    }
    stamp_create(plan)
    TRANSITION_PLANS[plan["id"]] = plan
    # Link to the IEP.
    iep["transition_plan_id"] = plan["id"]
    stamp_update(iep)
    return success_object(transition_plan_dto(plan), http_status=201)


@bp.route("/districts/<district_id>/students/<student_id>/ieps/<iep_id>/transition-plan/finalize",
          methods=["POST"])
def finalize_plan(district_id, student_id, iep_id):
    require_role(["SpecialEducationTeacher"])
    get_district(district_id)
    get_student(district_id, student_id)
    iep = get_iep(district_id, student_id, iep_id)
    plan = _existing_plan_for_iep(iep_id)
    if plan is None:
        raise APIError("ERR_TRANSITION_PLAN_NOT_FOUND", "TransitionPlan not found for IEP.")
    body = require_json_body()
    check_version(body.get("version"), plan.get("version", 1))

    if plan.get("status") != "DRAFT":
        raise APIError("ERR_TRANSITION_PLAN_NOT_DRAFT", "TransitionPlan is not in DRAFT.")
    if iep.get("status") not in ("DRAFT", "AMENDMENT_PENDING"):
        raise APIError("ERR_IEP_NOT_AMENDABLE_FOR_TRANSITION",
                       "IEP must be DRAFT or AMENDMENT_PENDING.")
    if not (plan.get("parent_invitation_documented") and plan.get("student_invitation_documented")):
        raise APIError("ERR_TRANSITION_INVITATIONS_MISSING",
                       "Both parent and student invitation flags must be true.")
    if not isinstance(plan.get("post_secondary_goal"), str) or len(plan["post_secondary_goal"]) < 10:
        raise APIError("ERR_INVALID_REQUEST", "post_secondary_goal length must be >= 10.")
    if not isinstance(plan.get("required_courses"), list) or len(plan["required_courses"]) == 0:
        raise APIError("ERR_INVALID_REQUEST", "required_courses must be non-empty.")

    plan["status"] = "FINALIZED"
    stamp_update(plan)
    return success_object(transition_plan_dto(plan))


@bp.route("/districts/<district_id>/students/<student_id>/ieps/<iep_id>/transition-plan", methods=["GET"])
def get_plan(district_id, student_id, iep_id):
    user_id, role = require_role(["DistrictAdmin", "SpecialEducationTeacher",
                                  "RelatedServiceProvider", "Parent"])
    student = get_student(district_id, student_id)
    if role == "Parent" and user_id != student.get("parent_user_id"):
        raise APIError("ERR_PARENT_OWNERSHIP_MISMATCH", "Parent may only act on their own student.")
    get_iep(district_id, student_id, iep_id)
    plan = _existing_plan_for_iep(iep_id)
    if plan is None:
        raise APIError("ERR_TRANSITION_PLAN_NOT_FOUND", "TransitionPlan not found for IEP.")
    return success_object(transition_plan_dto(plan))
