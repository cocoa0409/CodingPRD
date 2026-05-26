"""Student + AllergyProfile routes."""
from flask import Blueprint, request
import db
from response import success_object, success_array
from middleware import require_role
from validation import (
    parse_pagination, get_json_body, enforce_keys, require_str, require_int,
)
from services import (
    common_fields_init, bump_version, get_or_404, sort_by_created_at, paginate, clean,
    cascade_allergen_check_for_student,
)
from errors import ERR_INVALID_REQUEST, ERR_NOT_RESOURCE_OWNER, raise_err

bp = Blueprint("students", __name__)

ALLERGEN_ENUM = {"PEANUT", "TREE_NUT", "MILK", "EGG", "SOY", "WHEAT", "FISH", "SHELLFISH"}
SEVERITY_ENUM = {"MILD", "MODERATE", "SEVERE_ANAPHYLACTIC"}


# --------------------------- Student --------------------------------

@bp.post("/school-meals/students")
def create_student():
    require_role({"SchoolStaff"})
    body = get_json_body()
    enforce_keys(body, required={"household_id", "full_name", "school_code", "grade_level"}, optional=set())
    require_str(body["household_id"], "household_id")
    require_str(body["full_name"], "full_name")
    require_str(body["school_code"], "school_code")
    require_int(body["grade_level"], "grade_level", min_val=0, max_val=12)
    get_or_404(db.households, body["household_id"], "Household")
    rec = {
        **common_fields_init(),
        "household_id": body["household_id"],
        "full_name": body["full_name"],
        "school_code": body["school_code"],
        "grade_level": body["grade_level"],
    }
    db.students[rec["id"]] = rec
    return success_object(clean(rec), status=201)


@bp.get("/school-meals/students/<sid>")
def read_student(sid):
    user_id, role = require_role({"Parent", "SchoolStaff", "DistrictReviewer", "USDAAuditor"})
    rec = get_or_404(db.students, sid, "Student")
    if role == "Parent" and user_id != rec["household_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this student")
    return success_object(clean(rec))


@bp.get("/school-meals/students")
def list_students():
    require_role({"SchoolStaff", "DistrictReviewer", "USDAAuditor"})
    limit, offset = parse_pagination()
    household_id = request.args.get("household_id")
    school_code = request.args.get("school_code")
    items = list(db.students.values())
    if household_id is not None:
        items = [s for s in items if s["household_id"] == household_id]
    if school_code is not None:
        items = [s for s in items if s["school_code"] == school_code]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_array([clean(r) for r in page], limit=limit, offset=offset, total_count=total)


@bp.get("/school-meals/students/<sid>/allergy-profile")
def get_student_allergy_profile(sid):
    user_id, role = require_role({"Parent", "SchoolStaff", "DistrictReviewer", "USDAAuditor"})
    rec = get_or_404(db.students, sid, "Student")
    if role == "Parent" and user_id != rec["household_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this student")
    limit, offset = parse_pagination()
    items = [a for a in db.allergy_profiles.values() if a["student_id"] == sid]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_array([clean(r) for r in page], limit=limit, offset=offset, total_count=total)


# --------------------------- AllergyProfile --------------------------------

@bp.post("/school-meals/allergy-profiles")
def create_allergy_profile():
    user_id, role = require_role({"SchoolStaff", "Parent"})
    body = get_json_body()
    enforce_keys(body, required={"student_id"}, optional={"allergens", "severity"})
    require_str(body["student_id"], "student_id")
    student = get_or_404(db.students, body["student_id"], "Student")
    if role == "Parent" and user_id != student["household_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this student")
    allergens = body.get("allergens", [])
    severity = body.get("severity", "MILD")
    _validate_allergens(allergens)
    _validate_severity(severity)
    rec = {
        **common_fields_init(),
        "student_id": body["student_id"],
        "allergens": list(allergens),
        "severity": severity,
    }
    db.allergy_profiles[rec["id"]] = rec
    cascade_allergen_check_for_student(body["student_id"])
    return success_object(clean(rec), status=201)


@bp.patch("/school-meals/allergy-profiles/<pid>")
def update_allergy_profile(pid):
    user_id, role = require_role({"Parent", "SchoolStaff"})
    rec = get_or_404(db.allergy_profiles, pid, "AllergyProfile")
    student = db.students.get(rec["student_id"])
    if role == "Parent" and student is not None and user_id != student["household_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this student")
    body = get_json_body()
    enforce_keys(body, required=set(), optional={"allergens", "severity"})
    if "allergens" in body:
        _validate_allergens(body["allergens"])
        rec["allergens"] = list(body["allergens"])
    if "severity" in body:
        _validate_severity(body["severity"])
        rec["severity"] = body["severity"]
    bump_version(rec)
    cascade_allergen_check_for_student(rec["student_id"])
    return success_object(clean(rec))


def _validate_allergens(allergens):
    if not isinstance(allergens, list):
        raise_err(ERR_INVALID_REQUEST, "allergens must be array")
    seen = set()
    for a in allergens:
        if not isinstance(a, str):
            raise_err(ERR_INVALID_REQUEST, "allergen entries must be strings")
        if a not in ALLERGEN_ENUM:
            raise_err(ERR_INVALID_REQUEST, f"invalid allergen: {a}")
        if a in seen:
            raise_err(ERR_INVALID_REQUEST, f"duplicate allergen: {a}")
        seen.add(a)


def _validate_severity(severity):
    if severity not in SEVERITY_ENUM:
        raise_err(ERR_INVALID_REQUEST, f"invalid severity: {severity}")
