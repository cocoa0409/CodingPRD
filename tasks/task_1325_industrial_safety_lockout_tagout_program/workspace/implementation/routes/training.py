"""Training records and competency currency (PRD 3.4)."""

from datetime import datetime, timedelta, timezone

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import auth, paginate, ALL_ROLES
from response import ok, ok_list
from services import core
from clock import CLOCK, fmt

bp = Blueprint("training_records", __name__)

_COURSES = ("LOTO_AUTHORIZED_INITIAL", "LOTO_AUTHORIZED_REFRESH", "LOTO_AFFECTED")
_MODES = ("IN_PERSON", "ONLINE")


@bp.route("/training-records", methods=["POST"])
def create_training():
    auth(["EHSManager"])
    body = core.body_json()
    employee_id = core.req_str(body, "employee_id")
    course_code = core.req_enum(body, "course_code", _COURSES)
    delivery_mode = core.req_enum(body, "delivery_mode", _MODES)
    emp = core.get_or_404("employees", employee_id, "Employee")
    now = CLOCK.now()
    t = core.stamp_new({
        "id": core.new_id(),
        "employee_id": emp["id"],
        "course_code": course_code,
        "delivery_mode": delivery_mode,
        "assigned_at": fmt(now),
        "due_at": fmt(now + timedelta(days=core.ASSIGNMENT_DUE_DAYS)),
        "completed_at": None,
        "expires_at": None,
        "status": "ASSIGNED",
    })
    db.DB["training_records"][t["id"]] = t
    return ok(core.training_view(t), 201)


@bp.route("/training-records", methods=["GET"])
def list_training():
    auth(ALL_ROLES)
    employee_id = request.args.get("employee_id")
    course_code = request.args.get("course_code")
    status = request.args.get("status")
    items = list(db.DB["training_records"].values())
    if employee_id is not None:
        items = [t for t in items if t["employee_id"] == employee_id]
    if course_code is not None:
        items = [t for t in items if t["course_code"] == course_code]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.training_view(t) for t in page], total, limit, offset)


@bp.route("/training-records/<tid>", methods=["GET"])
def get_training(tid):
    auth(ALL_ROLES)
    t = core.get_or_404("training_records", tid, "TrainingRecord")
    return ok(core.training_view(t))


@bp.route("/training-records/<tid>/complete", methods=["POST"])
def complete_training(tid):
    auth(["EHSManager"])
    t = core.get_or_404("training_records", tid, "TrainingRecord")
    if t["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ASSIGNED training record can be completed")
    now = CLOCK.now()
    t["completed_at"] = fmt(now)
    # calculations.training_expiry, variant selected by delivery_mode:
    if t["delivery_mode"] == "IN_PERSON":
        # ANNIVERSARY: exactly 365 days after the completion instant.
        t["expires_at"] = fmt(now + timedelta(days=core.WINDOW_DAYS))
    else:
        # CALENDAR: 23:59:59Z on Dec 31 of the year following completion.
        t["expires_at"] = fmt(datetime(now.year + 1, 12, 31, 23, 59, 59,
                                       tzinfo=timezone.utc))
    t["status"] = "COMPLETED"
    core.touch(t)
    return ok(core.training_view(t))
