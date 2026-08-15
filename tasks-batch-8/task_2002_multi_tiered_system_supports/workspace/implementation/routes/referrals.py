"""Special-education referral endpoints (lifecycle + flat aliases)."""

from datetime import timedelta

from flask import Blueprint, request

from db import DB
from errors import (
    err, ERR_REFERRAL_NOT_FOUND, ERR_STUDENT_NOT_FOUND, ERR_INVALID_STATE,
    ERR_SPED_REFERRAL_PRECONDITION,
)
from middleware import (
    require_role, ALL_ROLES, get_json_body, check_unknown_fields, require_fields,
    req_enum, req_date, paginate, touch, parse_date,
)
from response import success_object, success_list
from services import (
    DETERMINE_OUTCOMES, serialize_referral,
    resolve_student, resolve_referral, plans_of_student, referrals_of_student,
    has_open_referral, create_referral_with_cascade,
)

bp = Blueprint("referrals", __name__)


@bp.post("/districts/<districtId>/schools/<schoolId>/students/<studentId>/sped-referrals")
def create_referral(districtId, schoolId, studentId):
    require_role("TeamLead", "SpEdDirector")
    student = resolve_student(districtId, schoolId, studentId)
    district = DB.districts[districtId]
    # Referral precondition (PRD §3.9).
    if (student["current_tier"] != "TIER_3"
            or student["weeks_at_tier3_unresponsive"] < district["sped_referral_min_weeks"]
            or has_open_referral(studentId)):
        raise err(ERR_SPED_REFERRAL_PRECONDITION, 422,
                  "Student not at TIER_3 with sufficient unresponsive weeks, or an "
                  "open referral already exists")
    active_plan = next(
        (p for p in plans_of_student(studentId) if p["status"] == "ACTIVE"), None
    )
    ref = create_referral_with_cascade(student, active_plan)
    return success_object(serialize_referral(ref), status=201)


def _list_referrals(studentId):
    status_filter = request.args.get("status")
    items = referrals_of_student(studentId)
    if status_filter is not None:
        items = [r for r in items if r["status"] == status_filter]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_referral(r) for r in page], limit, offset, total)


@bp.get("/districts/<districtId>/schools/<schoolId>/students/<studentId>/sped-referrals")
def list_referrals(districtId, schoolId, studentId):
    require_role(*ALL_ROLES)
    resolve_student(districtId, schoolId, studentId)
    return _list_referrals(studentId)


@bp.get("/districts/<districtId>/schools/<schoolId>/students/<studentId>/sped-referrals/<referralId>")
def get_referral(districtId, schoolId, studentId, referralId):
    require_role(*ALL_ROLES)
    r = resolve_referral(districtId, schoolId, studentId, referralId)
    return success_object(serialize_referral(r))


@bp.post("/districts/<districtId>/schools/<schoolId>/students/<studentId>/sped-referrals/<referralId>/record-consent")
def record_consent(districtId, schoolId, studentId, referralId):
    require_role("SpEdDirector")
    body = get_json_body()
    check_unknown_fields(body, {"consent_received_on"})
    require_fields(body, ["consent_received_on"])
    consent_on = req_date(body, "consent_received_on")
    r = resolve_referral(districtId, schoolId, studentId, referralId)
    if r["status"] != "PENDING_CONSENT":
        raise err(ERR_INVALID_STATE, 409, "Only a PENDING_CONSENT referral can record consent")
    r["consent_received_on"] = consent_on
    r["evaluation_due_on"] = (parse_date(consent_on) + timedelta(days=60)).isoformat()
    r["status"] = "CONSENTED"
    touch(r)
    return success_object(serialize_referral(r))


@bp.post("/districts/<districtId>/schools/<schoolId>/students/<studentId>/sped-referrals/<referralId>/start-evaluation")
def start_evaluation(districtId, schoolId, studentId, referralId):
    require_role("SpEdDirector")
    r = resolve_referral(districtId, schoolId, studentId, referralId)
    if r["status"] != "CONSENTED":
        raise err(ERR_INVALID_STATE, 409, "Only a CONSENTED referral can start evaluation")
    r["status"] = "EVAL_IN_PROGRESS"
    touch(r)
    return success_object(serialize_referral(r))


@bp.post("/districts/<districtId>/schools/<schoolId>/students/<studentId>/sped-referrals/<referralId>/determine")
def determine_referral(districtId, schoolId, studentId, referralId):
    require_role("SpEdDirector")
    body = get_json_body()
    check_unknown_fields(body, {"outcome"})
    require_fields(body, ["outcome"])
    outcome = req_enum(body, "outcome", DETERMINE_OUTCOMES)
    r = resolve_referral(districtId, schoolId, studentId, referralId)
    if r["status"] != "EVAL_IN_PROGRESS":
        raise err(ERR_INVALID_STATE, 409, "Only an EVAL_IN_PROGRESS referral can be determined")
    r["status"] = outcome
    touch(r)
    if outcome == "ELIGIBLE":
        student = DB.students[studentId]
        if "IEP" not in student["subgroup_codes"]:
            student["subgroup_codes"].append("IEP")
            touch(student)
    return success_object(serialize_referral(r))


@bp.post("/districts/<districtId>/schools/<schoolId>/students/<studentId>/sped-referrals/<referralId>/withdraw")
def withdraw_referral(districtId, schoolId, studentId, referralId):
    require_role("SpEdDirector")
    r = resolve_referral(districtId, schoolId, studentId, referralId)
    if r["status"] not in ("PENDING_CONSENT", "CONSENTED"):
        raise err(ERR_INVALID_STATE, 409,
                  "Only PENDING_CONSENT or CONSENTED referrals can be withdrawn")
    r["status"] = "WITHDRAWN"
    touch(r)
    return success_object(serialize_referral(r))


# ---------- Flat aliases ----------

@bp.get("/sped-referrals/<referralId>")
def get_referral_flat(referralId):
    require_role(*ALL_ROLES)
    r = DB.sped_referrals.get(referralId)
    if r is None:
        raise err(ERR_REFERRAL_NOT_FOUND, 404, "referralId does not exist")
    return success_object(serialize_referral(r))


@bp.get("/students/<id>/sped-referrals")
def list_referrals_flat(id):
    require_role(*ALL_ROLES)
    st = DB.students.get(id)
    if st is None:
        raise err(ERR_STUDENT_NOT_FOUND, 404, "student id does not exist")
    return _list_referrals(id)
