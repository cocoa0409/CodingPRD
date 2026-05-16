"""District + clock + student routes."""

from flask import Blueprint

from core.auth import require_role
from core.envelope import success_object, success_array
from core.errors import APIError
from core.pagination import parse_pagination, paginate
from core.store import (
    DISTRICTS, STUDENTS, stamp_create, stamp_update,
)
from core.validation import (
    get_district, get_student, require_json_body, check_version,
)
from core.clock import CLOCK_EPOCH, advance_days

from services.cascades import auto_expire_eligible_ieps
from services.serializers import district_dto, student_dto


bp = Blueprint("districts", __name__)


# ---------- Districts ----------

@bp.route("/districts", methods=["POST"])
def create_district():
    require_role(["DistrictAdmin"])
    body = require_json_body()
    name = body.get("name")
    state_code = body.get("state_code")
    if not isinstance(name, str) or not name.strip():
        raise APIError("ERR_INVALID_REQUEST", "name is required and must be a non-empty string.")
    if not isinstance(state_code, str) or len(state_code) != 2 or not state_code.isalpha():
        raise APIError("ERR_INVALID_REQUEST", "state_code must be a two-letter US state code.")

    district = {
        "name": name,
        "state_code": state_code.upper(),
        "current_date": CLOCK_EPOCH,
    }
    stamp_create(district)
    DISTRICTS[district["id"]] = district
    return success_object(district_dto(district), http_status=201)


@bp.route("/districts/<district_id>", methods=["GET"])
def get_district_route(district_id):
    require_role(["DistrictAdmin", "SchoolPsychologist", "SpecialEducationTeacher",
                  "RelatedServiceProvider", "Parent"])
    district = get_district(district_id)
    # Parent must own at least one student in district? The PRD only requires ownership
    # for endpoints that operate on a specific Student. District-level GET is shared.
    return success_object(district_dto(district))


@bp.route("/districts/<district_id>/clock/advance", methods=["POST"])
def advance_clock(district_id):
    require_role(["DistrictAdmin"])
    district = get_district(district_id)
    body = require_json_body()
    by_days = body.get("by_days")
    check_version(body.get("version"), district.get("version", 1))
    if not isinstance(by_days, int) or isinstance(by_days, bool):
        raise APIError("ERR_INVALID_REQUEST", "by_days must be an integer.")
    if by_days < 1 or by_days > 3650:
        raise APIError("ERR_INVALID_REQUEST", "by_days must be between 1 and 3650.")

    district["current_date"] = advance_days(district["current_date"], by_days)
    stamp_update(district)

    # After clock advance: auto-expire eligible IEPs (cascade) for this district.
    auto_expire_eligible_ieps(district_id, district["current_date"])

    return success_object(district_dto(district))


# ---------- Students ----------

@bp.route("/districts/<district_id>/students", methods=["POST"])
def create_student(district_id):
    require_role(["DistrictAdmin"])
    get_district(district_id)
    body = require_json_body()

    external_student_number = body.get("external_student_number")
    date_of_birth = body.get("date_of_birth")
    parent_user_id = body.get("parent_user_id")
    if not isinstance(external_student_number, str) or not external_student_number.strip():
        raise APIError("ERR_INVALID_REQUEST", "external_student_number is required.")
    if not isinstance(date_of_birth, str) or not date_of_birth.strip():
        raise APIError("ERR_INVALID_REQUEST", "date_of_birth is required.")
    if not isinstance(parent_user_id, str) or not parent_user_id.strip():
        raise APIError("ERR_INVALID_REQUEST", "parent_user_id is required.")

    # Uniqueness of external_student_number within district.
    for s in STUDENTS.values():
        if s.get("district_id") == district_id and s.get("external_student_number") == external_student_number:
            raise APIError("ERR_INVALID_REQUEST", "external_student_number must be unique within district.")

    student = {
        "district_id": district_id,
        "external_student_number": external_student_number,
        "date_of_birth": date_of_birth,
        "parent_user_id": parent_user_id,
        "current_iep_id": None,
        "current_eligibility_evaluation_id": None,
        "triennial_reevaluation_due_date": None,
        "triennial_status": "NOT_APPLICABLE",
        "requires_transition_plan": False,
        "lre_classification": "NOT_APPLICABLE",
    }
    stamp_create(student)
    STUDENTS[student["id"]] = student
    return success_object(student_dto(student), http_status=201)


@bp.route("/districts/<district_id>/students", methods=["GET"])
def list_students(district_id):
    require_role(["DistrictAdmin", "SchoolPsychologist", "SpecialEducationTeacher",
                  "RelatedServiceProvider"])
    get_district(district_id)
    limit, offset = parse_pagination()
    triennial_status_q = request_args("triennial_status")
    lre_q = request_args("lre_classification")

    rows = [s for s in STUDENTS.values() if s.get("district_id") == district_id]
    rows.sort(key=lambda s: s.get("created_at", ""))
    # Compute lazy fields for filtering correctness.
    dtos = [student_dto(s) for s in rows]
    if triennial_status_q:
        dtos = [d for d in dtos if d.get("triennial_status") == triennial_status_q]
    if lre_q:
        dtos = [d for d in dtos if d.get("lre_classification") == lre_q]
    page, total = paginate(dtos, limit, offset)
    return success_array(page, limit=limit, offset=offset, total_count=total)


@bp.route("/districts/<district_id>/students/<student_id>", methods=["GET"])
def get_student_route(district_id, student_id):
    user_id, role = require_role(["DistrictAdmin", "SchoolPsychologist", "SpecialEducationTeacher",
                                  "RelatedServiceProvider", "Parent"])
    student = get_student(district_id, student_id)
    if role == "Parent" and user_id != student.get("parent_user_id"):
        raise APIError("ERR_PARENT_OWNERSHIP_MISMATCH", "Parent may only act on their own student.")
    return success_object(student_dto(student))


def request_args(key):
    """Thin re-export to keep blueprint files concise."""
    from flask import request
    val = request.args.get(key)
    return val if val else None
