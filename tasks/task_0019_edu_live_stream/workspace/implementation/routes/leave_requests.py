"""LeaveRequest endpoints."""
from flask import Blueprint, request

from db import bump, make_common_fields, make_immutable_fields, store
from errors import raise_api
from middleware import require_roles
from response import success
from services.lookup import get_enrollment, get_leave_request, get_live_class

leave_requests_bp = Blueprint("leave_requests", __name__)


@leave_requests_bp.route("/leave-requests", methods=["POST"])
def create_leave_request():
    user_id, _ = require_roles("Student")
    body = request.get_json(silent=True) or {}
    enrollment_id = body.get("enrollment_id")
    live_class_id = body.get("live_class_id")
    reason = body.get("reason")
    if not enrollment_id:
        raise_api("ERR_ENROLLMENT_NOT_FOUND", "enrollment_id required")
    if not live_class_id:
        raise_api("ERR_LIVE_CLASS_NOT_FOUND", "live_class_id required")
    if not reason or not isinstance(reason, str):
        raise_api("ERR_INVALID_PRICING", "reason required")
    enr = get_enrollment(enrollment_id)
    if enr["student_id"] != user_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the enrollment owner")
    lc = get_live_class(live_class_id)
    if lc["course_id"] != enr["course_id"]:
        raise_api("ERR_LIVE_CLASS_NOT_FOUND", "LiveClass not in enrollment's course")
    lr = {
        **make_common_fields(),
        "enrollment_id": enrollment_id,
        "live_class_id": live_class_id,
        "reason": reason,
        "status": "PENDING",
    }
    store.leave_requests[lr["id"]] = lr
    return success(dict(lr), http_status=201)


@leave_requests_bp.route("/leave-requests/<lr_id>/approve", methods=["POST"])
def approve_leave(lr_id):
    user_id, _ = require_roles("TeachingAssistant")
    lr = get_leave_request(lr_id)
    if lr["status"] != "PENDING":
        raise_api("ERR_LEAVE_NOT_PENDING", "LeaveRequest must be PENDING")
    lc = get_live_class(lr["live_class_id"])
    if lc["status"] != "SCHEDULED":
        raise_api("ERR_LIVE_CLASS_ALREADY_STARTED", "LiveClass already started")
    enr = get_enrollment(lr["enrollment_id"])
    # TA scope: caller must be TA of the enrollment's class group
    if enr.get("class_group_id"):
        cg = store.class_groups.get(enr["class_group_id"])
        if not cg or cg.get("ta_instructor_id") != user_id:
            raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the class TA")
    else:
        # If no group assigned, TA still must be TA of some group on this course
        ok = any(
            cg.get("ta_instructor_id") == user_id
            for cg in store.class_groups.values()
            if cg["course_id"] == enr["course_id"]
        )
        if not ok:
            raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not a TA for this course")

    lr["status"] = "APPROVED"
    bump(lr)
    att = {
        **make_immutable_fields(),
        "live_class_id": lr["live_class_id"],
        "enrollment_id": lr["enrollment_id"],
        "mark": "EXCUSED",
        "checkin_method": "LEAVE",
        "checkin_ts": None,
        "code_provided": None,
    }
    store.attendances[att["id"]] = att
    return success(dict(lr))


@leave_requests_bp.route("/leave-requests/<lr_id>/reject", methods=["POST"])
def reject_leave(lr_id):
    user_id, _ = require_roles("TeachingAssistant")
    lr = get_leave_request(lr_id)
    if lr["status"] != "PENDING":
        raise_api("ERR_LEAVE_NOT_PENDING", "LeaveRequest must be PENDING")
    enr = get_enrollment(lr["enrollment_id"])
    if enr.get("class_group_id"):
        cg = store.class_groups.get(enr["class_group_id"])
        if not cg or cg.get("ta_instructor_id") != user_id:
            raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the class TA")
    else:
        ok = any(
            cg.get("ta_instructor_id") == user_id
            for cg in store.class_groups.values()
            if cg["course_id"] == enr["course_id"]
        )
        if not ok:
            raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not a TA for this course")
    lr["status"] = "REJECTED"
    bump(lr)
    return success(dict(lr))
