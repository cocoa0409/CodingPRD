"""AttendanceRecord — append-only session log (PRD §3.4, §2.4)."""
from flask import Blueprint

import errors
from db import db, stamp_create
from middleware import require_role
from response import success
from services import serialize
from services.common import get_json_body, lookup, require_fields, as_number, as_bool
from services.timeutil import parse_dt

bp = Blueprint("attendance", __name__)


@bp.post("/attendance-records")
def create_attendance():
    require_role("AdmissionsOfficer")
    body = get_json_body()
    require_fields(body, ["enrollment_id", "session_date", "present", "cumulative_progress_pct"])
    enrollment_id = body["enrollment_id"]
    if not isinstance(enrollment_id, str):
        raise errors.invalid_request("enrollment_id must be a string")
    e = lookup(db.enrollments, enrollment_id)

    present = as_bool(body, "present")
    progress = as_number(body, "cumulative_progress_pct", ge=0, le=100)
    session_date = body["session_date"]
    parse_dt(session_date, "session_date")  # validate format

    # recording is for an ACTIVE enrollment (PRD §3.4)
    if e["status"] != "ACTIVE":
        raise errors.invalid_state("Attendance can only be recorded for an ACTIVE enrollment")

    a = {
        "enrollment_id": enrollment_id,
        "session_date": session_date,
        "present": present,
        "cumulative_progress_pct": progress,
    }
    stamp_create(a, common_fields=False)  # id + created_at only (append-only log)
    db.attendance_records[a["id"]] = a
    return success(serialize.attendance_view(a), status=201)
