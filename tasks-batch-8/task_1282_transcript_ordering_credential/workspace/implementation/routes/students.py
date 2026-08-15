"""Student + StudentRecord endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import (
    STUDENT_STATUSES,
    emit_audit,
    get_student,
    records_of_student,
    ser_record,
    ser_student,
    sorted_created,
    stamp,
    touch,
)
from util import (
    as_bool,
    as_enum,
    as_int,
    as_iso_date,
    as_list,
    as_str,
    body,
    pagination_args,
    reject_unknown_fields,
    required,
)
from decimal import Decimal
from util import round_half_up

bp = Blueprint("students", __name__)

STAFF_READ = [
    "RegistrarAdmin",
    "RegistrarOperator",
    "RegistrarReviewer",
    "BursarOffice",
    "LibraryOffice",
    "ArchiveClerk",
]
RECORD_READ = ["RegistrarAdmin", "RegistrarOperator", "RegistrarReviewer", "Student"]


@bp.post("/registrar/students")
def create_student():
    user_id, role = auth(["RegistrarAdmin"])
    data = body()
    reject_unknown_fields(
        data,
        {
            "student_number",
            "full_name",
            "date_of_birth",
            "email",
            "status",
            "ferpa_restricted",
            "archived_record_flag",
        },
    )
    student_number = as_str(required(data, "student_number"), "student_number")
    full_name = as_str(required(data, "full_name"), "full_name")
    dob = as_iso_date(required(data, "date_of_birth"), "date_of_birth")
    email = as_str(required(data, "email"), "email")
    status = as_enum(data.get("status", "ACTIVE"), "status", STUDENT_STATUSES)
    ferpa = data.get("ferpa_restricted", False)
    if not isinstance(ferpa, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "ferpa_restricted must be a boolean")
    archived = data.get("archived_record_flag", False)
    if not isinstance(archived, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "archived_record_flag must be a boolean")

    # student_number: 6-12 alphanumeric, unique tenant-wide.
    if not (6 <= len(student_number) <= 12) or not student_number.isalnum():
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "student_number must be 6-12 alphanumeric characters",
        )
    for s in DB["students"].values():
        if s["student_number"] == student_number:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "student_number must be unique"
            )

    rec = {
        "id": new_id(),
        "student_number": student_number,
        "full_name": full_name,
        "date_of_birth": dob,
        "email": email,
        "status": status,
        "ferpa_restricted": ferpa,
        "archived_record_flag": archived,
    }
    stamp(rec)
    DB["students"][rec["id"]] = rec
    emit_audit("Student", rec["id"], role, user_id, "STUDENT_CREATED")
    return ok(ser_student(rec), status=201)


@bp.get("/registrar/students")
def list_students():
    auth(STAFF_READ)
    limit, offset = pagination_args()
    items = list(DB["students"].values())
    status_q = request.args.get("status")
    if status_q is not None:
        items = [s for s in items if s["status"] == status_q]
    ferpa_q = request.args.get("ferpa_restricted")
    if ferpa_q is not None:
        want = ferpa_q.lower() == "true"
        items = [s for s in items if s["ferpa_restricted"] == want]
    arch_q = request.args.get("archived_record_flag")
    if arch_q is not None:
        want = arch_q.lower() == "true"
        items = [s for s in items if s["archived_record_flag"] == want]
    items = sorted_created(items)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_student(s) for s in page], total, limit, offset)


@bp.get("/registrar/students/<sid>")
def get_one_student(sid):
    auth(STAFF_READ + ["Student"])
    return ok(ser_student(get_student(sid)))


@bp.patch("/registrar/students/<sid>")
def update_student(sid):
    user_id, role = auth(["RegistrarAdmin"])
    rec = get_student(sid)
    data = body()
    reject_unknown_fields(data, {"status", "ferpa_restricted", "archived_record_flag"})
    if "status" in data:
        rec["status"] = as_enum(data["status"], "status", STUDENT_STATUSES)
    if "ferpa_restricted" in data:
        rec["ferpa_restricted"] = as_bool(data["ferpa_restricted"], "ferpa_restricted")
    if "archived_record_flag" in data:
        rec["archived_record_flag"] = as_bool(
            data["archived_record_flag"], "archived_record_flag"
        )
    touch(rec)
    emit_audit("Student", rec["id"], role, user_id, "STUDENT_UPDATED")
    return ok(ser_student(rec))


@bp.get("/registrar/students/<sid>/records")
def list_student_records(sid):
    auth(RECORD_READ)
    rec = get_student(sid)
    limit, offset = pagination_args()
    items = sorted_created(records_of_student(rec["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_record(r) for r in page], total, limit, offset)


@bp.post("/registrar/students/<sid>/records")
def publish_student_record(sid):
    user_id, role = auth(["RegistrarAdmin"])
    student = get_student(sid)
    data = body()
    reject_unknown_fields(
        data, {"effective_term", "courses", "earned_credits", "degree_awarded"}
    )
    effective_term = as_str(required(data, "effective_term"), "effective_term")
    courses = as_list(required(data, "courses"), "courses")
    earned_credits = as_int(required(data, "earned_credits"), "earned_credits")
    degree_awarded = data.get("degree_awarded", False)
    if not isinstance(degree_awarded, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "degree_awarded must be a boolean")

    total_points = Decimal(0)
    total_credits = 0
    for c in courses:
        if not isinstance(c, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "courses entries must be objects")
        gp = c.get("grade_points")
        cr = c.get("credits")
        if isinstance(gp, bool) or not isinstance(gp, (int, float)):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "course.grade_points must be a number"
            )
        if isinstance(cr, bool) or not isinstance(cr, (int, float)):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "course.credits must be a number"
            )
        total_points += Decimal(str(gp)) * Decimal(str(cr))
        total_credits += cr
    if total_credits > 0:
        gpa_cents = round_half_up(
            Decimal(100) * total_points / Decimal(str(total_credits))
        )
    else:
        gpa_cents = 0

    prior = records_of_student(student["id"])
    record_version = max([r["record_version"] for r in prior], default=0) + 1
    rec = {
        "id": new_id(),
        "student_id": student["id"],
        "effective_term": effective_term,
        "gpa_cents": gpa_cents,
        "earned_credits": earned_credits,
        "degree_awarded": degree_awarded,
        "record_version": record_version,
        "is_current": True,
    }
    stamp(rec)
    DB["student_records"][rec["id"]] = rec
    for r in prior:
        if r["is_current"]:
            r["is_current"] = False
            touch(r)
    touch(student)
    return ok(ser_record(rec), status=201)
