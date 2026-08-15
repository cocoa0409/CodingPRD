"""Student endpoints: POST/GET/GET/PATCH /advising/students[...]"""
from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import get_auth_context, require_role
from response import success_object, success_list
from services.common import (
    body, get_pagination_params, paginate, require_fields, stamp_new, touch,
)
from services.calculations import (
    compute_advising_requirement_status, compute_registration_clearance,
    compute_at_risk_score, risk_tier_for,
)

bp = Blueprint("students", __name__)

ROLE_READ = ("AdvisingDirector", "Advisor", "FrontDeskStaff")


def student_public(s):
    return {
        "id": s["id"],
        "full_name": s["full_name"],
        "email": s["email"],
        "major_code": s["major_code"],
        "cohort_year": s["cohort_year"],
        "current_term_code": s["current_term_code"],
        "gpa": s["gpa"],
        "care_status": s["care_status"],
        "advising_required_flag": s["advising_required_flag"],
        "enrolled_term_codes": s["enrolled_term_codes"],
        "no_show_count": s["no_show_count"],
        "at_risk_score": s["at_risk_score"],
        "risk_tier": s["risk_tier"],
        "advising_requirement_status": s["advising_requirement_status"],
        "registration_clearance": s["registration_clearance"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def _validate_gpa(gpa):
    if isinstance(gpa, bool) or not isinstance(gpa, (int, float)):
        raise ApiError(errors.ERR_VALIDATION, "gpa must be a number", 400)
    if gpa < 0.0 or gpa > 4.0:
        raise ApiError(errors.ERR_VALIDATION, "gpa must be between 0.0 and 4.0 inclusive", 400)
    return float(gpa)


@bp.route("/advising/students", methods=["POST"])
def create_student():
    user_id, role = get_auth_context()
    data = body()
    require_fields(data, ["full_name", "email", "major_code", "cohort_year",
                          "current_term_code", "gpa"])
    if not isinstance(data["cohort_year"], int) or isinstance(data["cohort_year"], bool):
        raise ApiError(errors.ERR_VALIDATION, "cohort_year must be an integer", 400)
    gpa = _validate_gpa(data["gpa"])
    flag = data.get("advising_required_flag", False)
    if not isinstance(flag, bool):
        raise ApiError(errors.ERR_VALIDATION, "advising_required_flag must be a boolean", 400)
    require_role(role, ("AdvisingDirector", "FrontDeskStaff"))

    student = stamp_new({
        "full_name": data["full_name"],
        "email": data["email"],
        "major_code": data["major_code"],
        "cohort_year": data["cohort_year"],
        "current_term_code": data["current_term_code"],
        "gpa": gpa,
        "care_status": "ENROLLED",
        "advising_required_flag": flag,
        "enrolled_term_codes": [data["current_term_code"]],
        "no_show_count": 0,
    })
    db.students[student["id"]] = student
    # derived fields computed immediately
    student["at_risk_score"] = compute_at_risk_score(student["id"])
    student["risk_tier"] = risk_tier_for(student["at_risk_score"])
    student["advising_requirement_status"] = compute_advising_requirement_status(student)
    student["registration_clearance"] = compute_registration_clearance(student)
    return success_object(student_public(student), 201)


@bp.route("/advising/students", methods=["GET"])
def list_students():
    user_id, role = get_auth_context()
    require_role(role, ("AdvisingDirector", "Advisor", "FrontDeskStaff", "FacultyReferrer"))
    limit, offset = get_pagination_params()
    items = list(db.students.values())
    major_code = request.args.get("major_code")
    cohort_year = request.args.get("cohort_year")
    risk_tier = request.args.get("risk_tier")
    care_status = request.args.get("care_status")
    if major_code is not None:
        items = [s for s in items if s["major_code"] == major_code]
    if cohort_year is not None:
        try:
            cy = int(cohort_year)
        except (ValueError, TypeError):
            raise ApiError(errors.ERR_VALIDATION, "cohort_year must be an integer", 400)
        items = [s for s in items if s["cohort_year"] == cy]
    if risk_tier is not None:
        if risk_tier not in ("LOW", "MEDIUM", "HIGH"):
            raise ApiError(errors.ERR_VALIDATION, f"Invalid risk_tier filter: {risk_tier}", 400)
        items = [s for s in items if s["risk_tier"] == risk_tier]
    if care_status is not None:
        if care_status not in ("ENROLLED", "ON_LEAVE", "INACTIVE"):
            raise ApiError(errors.ERR_VALIDATION, f"Invalid care_status filter: {care_status}", 400)
        items = [s for s in items if s["care_status"] == care_status]
    page, total = paginate(items, limit, offset)
    return success_list([student_public(s) for s in page], limit, offset, total)


@bp.route("/advising/students/<id>", methods=["GET"])
def get_student(id):
    user_id, role = get_auth_context()
    require_role(role, ROLE_READ)
    student = db.students.get(id)
    if not student:
        raise ApiError(errors.ERR_STUDENT_NOT_FOUND, f"Student {id} not found", 404)
    return success_object(student_public(student))


@bp.route("/advising/students/<id>", methods=["PATCH"])
def patch_student(id):
    user_id, role = get_auth_context()
    data = body()
    if "care_status" in data and data["care_status"] not in ("ENROLLED", "ON_LEAVE", "INACTIVE"):
        raise ApiError(errors.ERR_VALIDATION, f"Invalid care_status: {data['care_status']}", 400)
    if "advising_required_flag" in data and not isinstance(data["advising_required_flag"], bool):
        raise ApiError(errors.ERR_VALIDATION, "advising_required_flag must be a boolean", 400)
    if "gpa" in data:
        _validate_gpa(data["gpa"])
    require_role(role, ("AdvisingDirector",))
    student = db.students.get(id)
    if not student:
        raise ApiError(errors.ERR_STUDENT_NOT_FOUND, f"Student {id} not found", 404)

    term_changed = False
    if "current_term_code" in data and data["current_term_code"] != student["current_term_code"]:
        new_term = data["current_term_code"]
        student["current_term_code"] = new_term
        term_changed = True
        if student["care_status"] == "ENROLLED" and new_term not in student["enrolled_term_codes"]:
            student["enrolled_term_codes"].append(new_term)
    if "advising_required_flag" in data:
        student["advising_required_flag"] = data["advising_required_flag"]
    if "care_status" in data:
        student["care_status"] = data["care_status"]
    gpa_changed = False
    if "gpa" in data:
        student["gpa"] = float(data["gpa"])
        gpa_changed = True

    # gpa change recomputes score/tier; flag or term changes recompute requirement/clearance
    if gpa_changed:
        from services.calculations import recompute_student_risk
        recompute_student_risk(id)
    else:
        from services.calculations import recompute_student_requirement_and_clearance
        recompute_student_requirement_and_clearance(id)

    touch(student)
    return success_object(student_public(student))
