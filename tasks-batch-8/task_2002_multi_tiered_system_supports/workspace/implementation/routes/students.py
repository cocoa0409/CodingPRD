"""Student endpoints (incl. flat aliases)."""

from flask import Blueprint, request

from db import DB
from errors import err, ERR_STUDENT_NOT_FOUND, ERR_SCHOOL_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import (
    require_role, ALL_ROLES, get_json_body, check_unknown_fields, require_fields,
    req_string, req_int, opt_enum_array, base_fields, paginate, sort_created,
)
from response import success_object, success_list
from services import (
    SUBGROUP_SET, serialize_student, resolve_school, resolve_student,
)

bp = Blueprint("students", __name__)


@bp.post("/districts/<districtId>/schools/<schoolId>/students")
def create_student(districtId, schoolId):
    require_role("DistrictCoordinator", "SchoolRegistrar")
    body = get_json_body()
    check_unknown_fields(body, {"full_name", "grade_level", "subgroup_codes"})
    require_fields(body, ["full_name", "grade_level"])
    full_name = req_string(body, "full_name")
    grade_level = req_int(body, "grade_level")
    if not (0 <= grade_level <= 12):
        raise err(ERR_INVALID_REQUEST, 400, "grade_level must be between 0 (K) and 12")
    subgroup_codes = opt_enum_array(body, "subgroup_codes", SUBGROUP_SET, default=[])
    resolve_school(districtId, schoolId)
    st = base_fields()
    st.update({
        "school_id": schoolId,
        "full_name": full_name,
        "grade_level": grade_level,
        "subgroup_codes": subgroup_codes,
        "current_tier": "TIER_1",
        "weeks_at_tier3_unresponsive": 0,
    })
    DB.students[st["id"]] = st
    return success_object(serialize_student(st), status=201)


def _list_students(schoolId):
    q = request.args
    items = [st for st in DB.students.values() if st["school_id"] == schoolId]
    tier = q.get("current_tier")
    if tier is not None:
        items = [st for st in items if st["current_tier"] == tier]
    gl = q.get("grade_level")
    if gl is not None:
        try:
            gl_int = int(gl)
        except ValueError:
            raise err(ERR_INVALID_REQUEST, 400, "grade_level filter must be an integer")
        items = [st for st in items if st["grade_level"] == gl_int]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_student(st) for st in page], limit, offset, total)


@bp.get("/districts/<districtId>/schools/<schoolId>/students")
def list_students(districtId, schoolId):
    require_role(*ALL_ROLES)
    resolve_school(districtId, schoolId)
    return _list_students(schoolId)


@bp.get("/districts/<districtId>/schools/<schoolId>/students/<studentId>")
def get_student(districtId, schoolId, studentId):
    require_role(*ALL_ROLES)
    st = resolve_student(districtId, schoolId, studentId)
    return success_object(serialize_student(st))


@bp.get("/students/<studentId>")
def get_student_flat(studentId):
    require_role(*ALL_ROLES)
    st = DB.students.get(studentId)
    if st is None:
        raise err(ERR_STUDENT_NOT_FOUND, 404, "studentId does not exist")
    return success_object(serialize_student(st))


@bp.get("/schools/<id>/students")
def list_students_flat(id):
    require_role(*ALL_ROLES)
    s = DB.schools.get(id)
    if s is None:
        raise err(ERR_SCHOOL_NOT_FOUND, 404, "school id does not exist")
    return _list_students(id)
