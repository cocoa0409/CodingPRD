"""AttendanceRecord endpoints (PRD section 3.5)."""

import db
import services
from errors import ApiError, ERR_INVALID_STATE
from middleware import authenticate
from response import success_obj, success_list
from routes import make_blueprint
from util import (
    body_json, check_shape, pagination_params, paginate, apply_filters,
    require_fk, exist_body_fks,
)

bp = make_blueprint("attendance")

ATTENDANCE_READ_ROLES = ["PlatformAdmin", "EnrollmentOfficer"]
EXCUSABLE_STATUSES = ("PRESENT", "PARTIAL", "ABSENT_UNEXCUSED")


@bp.post("/attendance")
def create_attendance():
    authenticate(["EnrollmentOfficer", "PlatformAdmin"])
    body = body_json()
    exist_body_fks(body, {"student_id": ("students", "student")})
    check_shape(body, {
        "student_id": {"type": "string", "required": True},
        "attendance_date": {"type": "datetime", "required": True},
        "synchronous_minutes": {"type": "integer", "required": True, "min": 0},
        "engagement_check_ins": {"type": "integer", "required": True, "min": 0},
    })
    status = services.attendance_determination(
        body["synchronous_minutes"], body["engagement_check_ins"])
    record = db.new_entity("attendance_records", {
        "student_id": body["student_id"],
        "attendance_date": body["attendance_date"],
        "synchronous_minutes": body["synchronous_minutes"],
        "engagement_check_ins": body["engagement_check_ins"],
        "attendance_status": status,
        "excused_reason": None,
    })
    if status == "ABSENT_UNEXCUSED":
        # Recording an unexcused absence immediately recomputes truancy.
        student = db.get("students", body["student_id"])
        if student is not None:
            services.recompute_truancy(student)
    return success_obj(db.public(record), 201)


@bp.get("/attendance/<aid>")
def get_attendance(aid):
    authenticate(ATTENDANCE_READ_ROLES)
    record = require_fk("attendance_records", aid, "attendance record")
    return success_obj(db.public(record), 200)


@bp.get("/students/<sid>/attendance")
def list_student_attendance(sid):
    authenticate(ATTENDANCE_READ_ROLES)
    student = require_fk("students", sid, "student")
    limit, offset = pagination_params()
    items = [r for r in db.all_of("attendance_records")
             if r["student_id"] == student["id"]]
    items = apply_filters(items, ["attendance_status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(r) for r in page], limit, offset, total, has_more)


@bp.post("/attendance/<aid>/excuse")
def excuse_attendance(aid):
    authenticate(["EnrollmentOfficer"])
    record = require_fk("attendance_records", aid, "attendance record")
    # State admissibility (priority 5) ahead of input shape (priority 16).
    if record["attendance_status"] not in EXCUSABLE_STATUSES:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "record status does not admit excusal")
    body = body_json()
    check_shape(body, {
        "excused_reason": {"type": "string", "required": True},
    })
    record["attendance_status"] = "ABSENT_EXCUSED"
    record["excused_reason"] = body["excused_reason"]
    db.touch(record)
    student = db.get("students", record["student_id"])
    if student is not None:
        services.recompute_truancy(student)
    return success_obj(db.public(record), 200)
