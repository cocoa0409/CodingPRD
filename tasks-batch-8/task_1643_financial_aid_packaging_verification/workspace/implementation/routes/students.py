"""Student endpoints (PRD 3.2) plus student-scoped sub-resource listings."""
import re

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_FIELD_CONSTRAINT,
    ERR_DUPLICATE,
)
from middleware import authorized, check_student_owns
from response import success_object
from routes.helpers import list_response
from services.calc import evaluate_sap
from services.core import new_record, public, touch
from validate import (
    get_body, req_str, req_int, req_enum, opt_int,
    require_path_resource,
)

bp = Blueprint("students", __name__)

DIRECTOR = ["AidDirector"]
OFFICER = ["AidOfficer"]
DIRECTOR_OFFICER = ["AidDirector", "AidOfficer"]
RESIDENCIES = ("IN_STATE", "OUT_OF_STATE")
DEPENDENCIES = ("DEPENDENT", "INDEPENDENT")
ENROLLMENTS = ("FULL_TIME", "THREE_QUARTER", "HALF_TIME", "LESS_THAN_HALF")
SSN_RE = re.compile(r"^\d{9}$")


@bp.post("/students")
def create_student():
    authorized(OFFICER)
    body = get_body()
    # Rung 9: shape.
    ssn = req_str(body, "ssn")
    if not SSN_RE.match(ssn):
        raise_error(ERR_INVALID_REQUEST, "ssn must be nine digits with no separators")
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    residency = req_enum(body, "residency", RESIDENCIES)
    dependency_status = req_enum(body, "dependency_status", DEPENDENCIES)
    enrollment_status = req_enum(body, "enrollment_status", ENROLLMENTS)
    grade_level = req_int(body, "grade_level", minimum=1, maximum=5)
    attempted = opt_int(body, "cumulative_attempted_credits", 0, minimum=0)
    completed = opt_int(body, "cumulative_completed_credits", 0, minimum=0)
    max_timeframe = opt_int(body, "max_timeframe_credits", 180, minimum=0)
    gpa = opt_int(body, "gpa_hundredths", 0, minimum=0)
    # Rung 10: the completed figure may never exceed the attempted figure.
    if completed > attempted:
        raise_error(ERR_FIELD_CONSTRAINT,
                    "cumulative_completed_credits may not exceed cumulative_attempted_credits")
    # Rung 11: uniqueness.
    for s in db.students.values():
        if s["ssn"] == ssn:
            raise_error(ERR_DUPLICATE, f"ssn {ssn} is already registered")
        if s["email"] == email:
            raise_error(ERR_DUPLICATE, f"email {email} is already registered")
    rec = new_record("students", {
        "ssn": ssn,
        "full_name": full_name,
        "email": email,
        "residency": residency,
        "dependency_status": dependency_status,
        "enrollment_status": enrollment_status,
        "grade_level": grade_level,
        "sap_status": "NOT_EVALUATED",
        "cumulative_attempted_credits": attempted,
        "cumulative_completed_credits": completed,
        "max_timeframe_credits": max_timeframe,
        "gpa_hundredths": gpa,
    })
    return success_object(public(rec), status=201)


@bp.get("/students")
def list_students():
    authorized(DIRECTOR_OFFICER)
    return list_response("students", {
        "sap_status": request.args.get("sap_status"),
        "enrollment_status": request.args.get("enrollment_status"),
    })


@bp.get("/students/<rid>")
def get_student(rid):
    caller = authorized(["AidDirector", "AidOfficer", "Student"])
    rec = require_path_resource("students", rid)
    check_student_owns(caller, rec["id"])
    return success_object(public(rec))


@bp.patch("/students/<rid>")
def patch_student(rid):
    authorized(OFFICER)
    rec = require_path_resource("students", rid)
    body = get_body()
    if "enrollment_status" in body and body["enrollment_status"] is not None:
        rec["enrollment_status"] = req_enum(body, "enrollment_status", ENROLLMENTS)
    if "grade_level" in body and body["grade_level"] is not None:
        rec["grade_level"] = req_int(body, "grade_level", minimum=1, maximum=5)
    if "residency" in body and body["residency"] is not None:
        rec["residency"] = req_enum(body, "residency", RESIDENCIES)
    if "cumulative_attempted_credits" in body and body["cumulative_attempted_credits"] is not None:
        rec["cumulative_attempted_credits"] = req_int(
            body, "cumulative_attempted_credits", minimum=0)
    if "cumulative_completed_credits" in body and body["cumulative_completed_credits"] is not None:
        rec["cumulative_completed_credits"] = req_int(
            body, "cumulative_completed_credits", minimum=0)
    if "gpa_hundredths" in body and body["gpa_hundredths"] is not None:
        rec["gpa_hundredths"] = req_int(body, "gpa_hundredths", minimum=0)
    if "max_timeframe_credits" in body and body["max_timeframe_credits"] is not None:
        rec["max_timeframe_credits"] = req_int(body, "max_timeframe_credits", minimum=0)
    # The completed figure may never exceed the attempted figure (PRD 3.2).
    if rec["cumulative_completed_credits"] > rec["cumulative_attempted_credits"]:
        raise_error(ERR_FIELD_CONSTRAINT,
                    "cumulative_completed_credits may not exceed cumulative_attempted_credits")
    touch(rec)
    return success_object(public(rec))


@bp.post("/students/<rid>/evaluate-sap")
def evaluate_sap_endpoint(rid):
    authorized(OFFICER)
    rec = require_path_resource("students", rid)
    body = get_body()
    transfer = opt_int(body, "transfer_credits", 0, minimum=0)
    rec["sap_status"] = evaluate_sap(rec, transfer)
    touch(rec)
    return success_object(public(rec))


@bp.post("/students/<rid>/sap-appeal")
def sap_appeal(rid):
    authorized(DIRECTOR)
    rec = require_path_resource("students", rid)
    if rec["sap_status"] != "SUSPENDED":
        raise_error(ERR_INVALID_STATE,
                    f"sap_status is {rec['sap_status']}, expected SUSPENDED")
    body = get_body()
    req_str(body, "appeal_reason")
    rec["sap_status"] = "APPEAL_APPROVED"
    touch(rec)
    return success_object(public(rec))


# ---------------------------------------------------------------------------
# Student-scoped sub-resource listings
# ---------------------------------------------------------------------------

@bp.get("/students/<rid>/isir-records")
def student_isir_records(rid):
    authorized(DIRECTOR_OFFICER)
    require_path_resource("students", rid)
    return list_response("isir_records", {
        "student_id": rid,
        "aid_year_id": request.args.get("aid_year_id"),
    })


@bp.get("/students/<rid>/verification-cases")
def student_verification_cases(rid):
    authorized(DIRECTOR_OFFICER)
    require_path_resource("students", rid)
    return list_response("verification_cases", {
        "student_id": rid,
        "aid_year_id": request.args.get("aid_year_id"),
    })


@bp.get("/students/<rid>/award-packages")
def student_award_packages(rid):
    caller = authorized(["AidDirector", "AidOfficer", "Student"])
    require_path_resource("students", rid)
    check_student_owns(caller, rid)
    return list_response("award_packages", {
        "student_id": rid,
        "aid_year_id": request.args.get("aid_year_id"),
    })


@bp.get("/students/<rid>/external-aid")
def student_external_aid(rid):
    authorized(DIRECTOR_OFFICER)
    require_path_resource("students", rid)
    return list_response("external_aid", {
        "student_id": rid,
        "aid_year_id": request.args.get("aid_year_id"),
    })


@bp.get("/students/<rid>/overaward-cases")
def student_overaward_cases(rid):
    authorized(DIRECTOR_OFFICER)
    require_path_resource("students", rid)
    return list_response("overaward_cases", {
        "student_id": rid,
        "aid_year_id": request.args.get("aid_year_id"),
    })


@bp.get("/students/<rid>/pj-cases")
def student_pj_cases(rid):
    authorized(DIRECTOR_OFFICER)
    require_path_resource("students", rid)
    return list_response("pj_cases", {
        "student_id": rid,
        "aid_year_id": request.args.get("aid_year_id"),
    })


@bp.get("/students/<rid>/conflicting-info-cases")
def student_conflicting_info_cases(rid):
    authorized(DIRECTOR_OFFICER)
    require_path_resource("students", rid)
    return list_response("conflicting_info_cases", {
        "student_id": rid,
        "aid_year_id": request.args.get("aid_year_id"),
    })
