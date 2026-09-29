"""VCP enrollments: application, eligibility, completion and withdrawal."""

from flask import Blueprint

import db
import response
import validation as V
from errors import ApiError
from middleware import actor_id, endpoint
from routes.common import fetch, require_owner
from services import derive
from services.constants import ELIGIBILITY_DECISIONS, PROGRAM_TRACKS
from services.serialize import dump_enrollment

bp = Blueprint("enrollments", __name__)

READ_ROLES = ["Redeveloper", "EnvironmentalConsultant", "StateAgencyReviewer",
              "Insurer", "Lender"]

PLAN_NON_TERMINAL = ("DRAFT", "SUBMITTED", "UNDER_TECHNICAL_REVIEW",
                     "PUBLIC_COMMENT", "REVISION_REQUESTED")


@bp.post("/vcp-enrollments")
@endpoint(["Redeveloper"])
def create_enrollment():
    body = V.json_body()
    site_id = V.id_field(body, "site_id", True)
    program_track = V.enum_field(body, "program_track", PROGRAM_TRACKS, True)
    statement = V.string_field(body, "applicant_statement", True, 1, 600)

    site = fetch("sites", site_id)
    require_owner(site)
    derive.assert_not_frozen(site)
    if site["delineation_status"] == "NONE":
        raise ApiError("ERR_DELINEATION_REQUIRED",
                       "The parcel must be screened before an application may "
                       "be filed.")

    row = db.insert("vcp_enrollments", {
        "site_id": site["id"],
        "program_track": program_track,
        "applicant_statement": statement,
        "status": "APPLIED",
        "enrolled_on": None,
        "eligibility_decided_by_user_id": None,
        "completion_requested_at": None,
        "reverted_completion_count": 0,
    })
    row["status"] = "ELIGIBILITY_REVIEW"
    return response.created(dump_enrollment(row))


@bp.get("/vcp-enrollments/<enrollment_id>")
@endpoint(READ_ROLES)
def get_enrollment(enrollment_id):
    return response.object_response(
        dump_enrollment(fetch("vcp_enrollments", enrollment_id)))


@bp.post("/vcp-enrollments/<enrollment_id>/eligibility-decision")
@endpoint(["StateAgencyReviewer"])
def eligibility_decision(enrollment_id):
    body = V.json_body()
    decision = V.enum_field(body, "decision", ELIGIBILITY_DECISIONS, True)
    V.string_field(body, "decision_note", False, 1, 600)

    enrollment = fetch("vcp_enrollments", enrollment_id)
    site = db.get("sites", enrollment["site_id"])
    if decision == "ENROLL" and site is not None:
        derive.assert_not_frozen(site)
    if enrollment["status"] != "ELIGIBILITY_REVIEW":
        raise ApiError("ERR_INVALID_ENROLLMENT_STATE",
                       "Eligibility has already been decided.")

    if decision == "REJECT":
        enrollment["status"] = "REJECTED"
        enrollment["eligibility_decided_by_user_id"] = actor_id()
        db.touch(enrollment)
        return response.object_response(dump_enrollment(enrollment))

    protection = derive.protection_for_site(enrollment["site_id"])
    if protection is None or protection["inquiry_state"] != "AAI_COMPLETE":
        raise ApiError("ERR_ENROLLMENT_NOT_ELIGIBLE",
                       "The parcel's all-appropriate-inquiries record is not "
                       "complete.")
    if (enrollment["program_track"] == "RESTRICTED_CLOSURE"
            and site is not None
            and not site["institutional_control_committed"]):
        raise ApiError("ERR_CONTROL_COMMITMENT_MISSING",
                       "A RESTRICTED_CLOSURE track requires the parcel's "
                       "institutional control commitment.")
    enrollment["status"] = "ENROLLED"
    enrollment["enrolled_on"] = db.today_str()
    enrollment["eligibility_decided_by_user_id"] = actor_id()
    db.touch(enrollment)
    return response.object_response(dump_enrollment(enrollment))


@bp.post("/vcp-enrollments/<enrollment_id>/completion-request")
@endpoint(["Redeveloper"])
def completion_request(enrollment_id):
    enrollment = fetch("vcp_enrollments", enrollment_id)
    site = db.get("sites", enrollment["site_id"])
    if site is not None:
        require_owner(site)
        derive.assert_not_frozen(site)
        derive.assert_posture_open(site)
    if enrollment["status"] != "IMPLEMENTATION":
        raise ApiError("ERR_INVALID_ENROLLMENT_STATE",
                       "Completion may only be requested from IMPLEMENTATION.")

    goals = derive.goals_of_site(enrollment["site_id"])
    if any(g["attainment_status"] != "ATTAINED" for g in goals):
        raise ApiError("ERR_GOALS_NOT_ATTAINED",
                       "Every cleanup goal must be ATTAINED before completion.")
    plan = derive.approved_plan_of_enrollment(enrollment["id"])
    if plan is not None:
        for control in derive.controls_of_plan(plan["id"]):
            if control["status"] != "OPERATING":
                raise ApiError("ERR_CONTROLS_NOT_OPERATING",
                               "Every site control must be OPERATING before "
                               "completion.")

    enrollment["completion_requested_at"] = db.now_ts()
    enrollment["status"] = "COMPLETION_REVIEW"
    db.touch(enrollment)
    return response.object_response(dump_enrollment(enrollment))


@bp.post("/vcp-enrollments/<enrollment_id>/withdraw")
@endpoint(["Redeveloper"])
def withdraw_enrollment(enrollment_id):
    body = V.json_body()
    V.string_field(body, "withdrawal_reason", True, 1, 600)

    enrollment = fetch("vcp_enrollments", enrollment_id)
    site = db.get("sites", enrollment["site_id"])
    if site is not None:
        require_owner(site)
        derive.assert_not_frozen(site)
    if enrollment["status"] != "ENROLLED":
        raise ApiError("ERR_INVALID_ENROLLMENT_STATE",
                       "Only an ENROLLED enrollment may be withdrawn.")
    plans = derive.plans_of_enrollment(enrollment["id"])
    if any(p["status"] == "APPROVED" for p in plans):
        raise ApiError("ERR_APPROVED_PLAN_EXISTS",
                       "An approved remedy bars withdrawal.")

    for plan in plans:
        if plan["status"] not in PLAN_NON_TERMINAL:
            continue
        plan["status"] = "WITHDRAWN"
        db.touch(plan)
        for policy in db.ordered(db.all_rows("cost_cap_policies")):
            if (policy["remedial_action_plan_id"] == plan["id"]
                    and policy["status"] == "QUOTED"):
                policy["status"] = "CANCELLED"
                db.touch(policy)

    enrollment["status"] = "WITHDRAWN"
    db.touch(enrollment)
    return response.object_response(dump_enrollment(enrollment))
