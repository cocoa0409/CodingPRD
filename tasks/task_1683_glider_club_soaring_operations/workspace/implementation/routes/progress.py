"""StudentProgress endpoints: open, signoff, verify, return-for-rework, reject."""

import uuid

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_MEMBER_NOT_ACTIVE,
    ERR_NOT_ENDORSING_INSTRUCTOR,
    ERR_PROGRESS_NOT_PENDING,
    ERR_PROGRESS_NOT_SIGNED_OFF,
    ERR_REFERENTIAL_INTEGRITY,
    ERR_RESOURCE_NOT_FOUND,
    ERR_SOLO_ELIGIBILITY_FAILED,
)
from middleware import auth, require_role
from response import success
from services import (
    ser_progress,
    set_badge_level,
    solo_eligible,
    dual_hours_total,
    touch,
)
from util import get_body, need_str, paginate, sort_items

bp = Blueprint("progress", __name__)

KINDS = (
    "SOLO_SIGNOFF",
    "CHECKRIDE_PASS",
    "BADGE_A",
    "BADGE_B",
    "BADGE_C",
    "BADGE_BRONZE",
    "BADGE_SILVER",
)


def _get_record_or_404(pid):
    record = db.STORE["progress"].get(pid)
    if record is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "StudentProgress not found")
    return record


@bp.post("/soaring/student-progress")
def create_progress():
    _, role = auth()
    require_role(role, ["Instructor", "ClubAdmin"])
    body = get_body()
    student_id = need_str(body, "student_id")
    instructor_id = need_str(body, "instructor_id")
    kind = need_str(body, "kind")
    student = db.STORE["members"].get(student_id)
    if student is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Student member not found")
    instructor = db.STORE["members"].get(instructor_id)
    if instructor is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Instructor member not found")
    if kind not in KINDS:
        raise ApiError(ERR_REFERENTIAL_INTEGRITY, 422, "Unknown progress kind")
    tier = db.STORE["tiers"].get(student["tier_id"])
    if tier is None or not tier["student_tier"]:
        raise ApiError(
            ERR_REFERENTIAL_INTEGRITY, 422,
            "The student's tier must have student_tier true",
        )
    if not instructor["is_instructor"]:
        raise ApiError(
            ERR_REFERENTIAL_INTEGRITY, 422,
            "instructor_id must reference a member with is_instructor true",
        )
    record = {
        "id": str(uuid.uuid4()),
        "student_id": student_id,
        "instructor_id": instructor_id,
        "kind": kind,
        "status": "PENDING",
        "dual_hours_at_signoff": None,
        "signed_off_at": None,
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.STORE["progress"][record["id"]] = record
    return success(ser_progress(record), "object", 201)


@bp.get("/soaring/student-progress")
def list_progress():
    auth()
    items = list(db.STORE["progress"].values())
    for param in ("student_id", "instructor_id", "status", "kind"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r.get(param) == value]
    page, meta = paginate(sort_items(items))
    return success([ser_progress(r) for r in page], "array", 200, meta)


@bp.get("/soaring/student-progress/<pid>")
def get_progress(pid):
    auth()
    return success(ser_progress(_get_record_or_404(pid)), "object", 200)


@bp.post("/soaring/student-progress/<pid>/signoff")
def signoff(pid):
    user_id, role = auth()
    require_role(role, ["Instructor"])
    record = _get_record_or_404(pid)
    if record["instructor_id"] != user_id:
        raise ApiError(
            ERR_NOT_ENDORSING_INSTRUCTOR, 403,
            "Only the record's endorsing instructor may sign it off",
        )
    if record["status"] != "PENDING":
        raise ApiError(
            ERR_PROGRESS_NOT_PENDING, 409,
            "Signoff requires StudentProgress status PENDING",
        )
    student = db.STORE["members"].get(record["student_id"])
    if record["kind"] == "SOLO_SIGNOFF":
        if student is None or student["status"] != "ACTIVE":
            raise ApiError(
                ERR_MEMBER_NOT_ACTIVE, 409,
                "The student must be ACTIVE at solo signoff",
            )
        if not solo_eligible(student, db.now()):
            raise ApiError(
                ERR_SOLO_ELIGIBILITY_FAILED, 422,
                "Dual hours below 10.0 or no dual flight within the "
                "trailing 90 days",
            )
    record["dual_hours_at_signoff"] = (
        float(dual_hours_total(record["student_id"]))
    )
    record["signed_off_at"] = db.now()
    record["status"] = "SIGNED_OFF"
    touch(record)
    return success(ser_progress(record), "object", 200)


@bp.post("/soaring/student-progress/<pid>/verify")
def verify(pid):
    _, role = auth()
    require_role(role, ["ClubAdmin"])
    record = _get_record_or_404(pid)
    if record["status"] != "SIGNED_OFF":
        raise ApiError(
            ERR_PROGRESS_NOT_SIGNED_OFF, 409,
            "Verify requires StudentProgress status SIGNED_OFF",
        )
    record["status"] = "VERIFIED"
    touch(record)
    student = db.STORE["members"].get(record["student_id"])
    if student is not None:
        if record["kind"] == "SOLO_SIGNOFF":
            if not student["solo_endorsed"]:
                student["solo_endorsed"] = True
                touch(student)
        elif record["kind"].startswith("BADGE_"):
            set_badge_level(student)
    return success(ser_progress(record), "object", 200)


@bp.post("/soaring/student-progress/<pid>/return-for-rework")
def return_for_rework(pid):
    _, role = auth()
    require_role(role, ["ClubAdmin"])
    record = _get_record_or_404(pid)
    if record["status"] != "SIGNED_OFF":
        raise ApiError(
            ERR_PROGRESS_NOT_SIGNED_OFF, 409,
            "Return-for-rework requires StudentProgress status SIGNED_OFF",
        )
    record["status"] = "PENDING"
    record["signed_off_at"] = None
    touch(record)
    return success(ser_progress(record), "object", 200)


@bp.post("/soaring/student-progress/<pid>/reject")
def reject(pid):
    _, role = auth()
    require_role(role, ["ClubAdmin"])
    record = _get_record_or_404(pid)
    if record["status"] != "PENDING":
        raise ApiError(
            ERR_PROGRESS_NOT_PENDING, 409,
            "Reject requires StudentProgress status PENDING",
        )
    record["status"] = "REJECTED"
    touch(record)
    return success(ser_progress(record), "object", 200)
