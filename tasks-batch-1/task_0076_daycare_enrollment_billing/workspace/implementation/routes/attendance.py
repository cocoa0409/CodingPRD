"""Attendance / check-in app endpoints."""
from __future__ import annotations

import re
from flask import Blueprint, g, request

from db import db, clock, now_iso
from middleware import require_roles, current_user_id
from response import ok_object, ok_array
from common import (
    base_entity, touch, public, get_or_404, get_body,
    require_str, optional_int, parse_pagination, paginate,
)
from errors import (
    APIError, ERR_REFERENCE_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_STATE, ERR_ALREADY_CHECKED_IN, ERR_INVALID_REQUEST,
)
from services.pricing import compute_late_fine, compute_cacfp

bp = Blueprint("attendance", __name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@bp.post("/attendance-records")
@require_roles("Teacher")
def create_attendance():
    body = get_body()
    enrollment_id = require_str(body, "enrollment_id")
    service_date = require_str(body, "service_date")
    sched = require_str(body, "scheduled_pickup_local")
    if not _DATE_RE.match(service_date):
        raise APIError(ERR_INVALID_REQUEST, 400, "service_date must be YYYY-MM-DD")
    if not _TIME_RE.match(sched):
        raise APIError(ERR_INVALID_REQUEST, 400, "scheduled_pickup_local must be HH:MM")
    enr = db.enrollments.get(enrollment_id)
    if enr is None:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 422, "enrollment_id does not exist")
    # Teacher owns the classroom of the enrollment (priority 6)
    if enr["classroom_id"] != current_user_id():
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Teacher does not own this classroom")
    mb = optional_int(body, "meals_breakfast", 0, minimum=0, maximum=1)
    ml = optional_int(body, "meals_lunch", 0, minimum=0, maximum=1)
    ms = optional_int(body, "meals_snack", 0, minimum=0, maximum=2)
    # at most one CHECKED_IN per enrollment per service_date (priority 12)
    for a in db.attendance_records.values():
        if a["enrollment_id"] == enrollment_id and a["service_date"] == service_date \
                and a["status"] == "CHECKED_IN":
            raise APIError(ERR_ALREADY_CHECKED_IN, 409, "Already checked in for this service date")
    ent = base_entity()
    ent.update({
        "enrollment_id": enrollment_id,
        "service_date": service_date,
        "scheduled_pickup_local": sched,
        "check_in_at": now_iso(),
        "check_out_at": None,
        "meals_breakfast": mb,
        "meals_lunch": ml,
        "meals_snack": ms,
        "late_pickup_minutes": 0,
        "late_fine_cents": 0,
        "cacfp_reimbursement_cents": 0,
        "status": "CHECKED_IN",
    })
    db.attendance_records[ent["id"]] = ent
    return ok_object(public(ent), 201)


@bp.get("/attendance-records")
@require_roles("CenterDirector", "BillingAdmin", "Teacher", "Parent")
def list_attendance():
    limit, offset = parse_pagination()
    enrollment_id = request.args.get("enrollment_id")
    service_date = request.args.get("service_date")
    rows = list(db.attendance_records.values())
    if enrollment_id is not None:
        rows = [a for a in rows if a["enrollment_id"] == enrollment_id]
    if service_date is not None:
        rows = [a for a in rows if a["service_date"] == service_date]
    if g.user_role == "Teacher":
        uid = current_user_id()
        rows = [a for a in rows
                if (e := db.enrollments.get(a["enrollment_id"])) is not None and e["classroom_id"] == uid]
    elif g.user_role == "Parent":
        uid = current_user_id()
        rows = [a for a in rows if _attendance_owned_by_family(a, uid)]
    rows.sort(key=lambda a: a["_seq"])
    page, total = paginate(rows, limit, offset)
    return ok_array([public(a) for a in page], limit, offset, total, 200)


def _attendance_owned_by_family(a, family_id):
    e = db.enrollments.get(a["enrollment_id"])
    if e is None:
        return False
    c = db.children.get(e["child_id"])
    return c is not None and c["family_id"] == family_id


@bp.get("/attendance-records/<rid>")
@require_roles("CenterDirector", "BillingAdmin", "Teacher", "Parent")
def get_attendance(rid):
    ent = get_or_404(db.attendance_records, rid, "attendance record")
    if g.user_role == "Teacher":
        e = db.enrollments.get(ent["enrollment_id"])
        if e is None or e["classroom_id"] != current_user_id():
            raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Teacher does not own this record")
    elif g.user_role == "Parent":
        if not _attendance_owned_by_family(ent, current_user_id()):
            raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Parent does not own this record")
    return ok_object(public(ent), 200)


@bp.post("/attendance-records/<rid>/check-out")
@require_roles("Teacher")
def check_out(rid):
    ent = get_or_404(db.attendance_records, rid, "attendance record")
    enr = db.enrollments.get(ent["enrollment_id"])
    # Teacher ownership (priority 6)
    if enr is None or enr["classroom_id"] != current_user_id():
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Teacher does not own this classroom")
    if ent["status"] != "CHECKED_IN" or ent["check_out_at"] is not None:
        raise APIError(ERR_INVALID_STATE, 409, "Record is not CHECKED_IN")
    classroom = db.classrooms.get(enr["classroom_id"])
    center = db.centers.get(classroom["center_id"])
    child = db.children.get(enr["child_id"])
    ent["check_out_at"] = now_iso()
    ent["status"] = "CHECKED_OUT"
    late_min, fine = compute_late_fine(ent, center)
    ent["late_pickup_minutes"] = late_min
    ent["late_fine_cents"] = fine
    ent["cacfp_reimbursement_cents"] = compute_cacfp(ent, child, center)
    touch(ent)
    return ok_object(public(ent), 200)
