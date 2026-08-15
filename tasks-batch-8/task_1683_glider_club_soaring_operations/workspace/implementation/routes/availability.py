"""InstructorAvailability endpoints."""

import uuid

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_REFERENTIAL_INTEGRITY,
    ERR_RESOURCE_NOT_FOUND,
)
from middleware import auth, forbid, require_role
from response import success
from services import ser_availability, touch
from util import get_body, need_dt, need_str, paginate, sort_items

bp = Blueprint("availability", __name__)


def _get_window_or_404(wid):
    window = db.STORE["availability"].get(wid)
    if window is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "InstructorAvailability not found")
    return window


@bp.post("/soaring/instructor-availability")
def create_window():
    user_id, role = auth()
    require_role(role, ["Instructor", "ClubAdmin"])
    body = get_body()
    instructor_id = need_str(body, "instructor_id")
    start_at = need_dt(body, "start_at")
    end_at = need_dt(body, "end_at")
    # An Instructor publishes windows for themselves; ClubAdmin for anyone.
    if role == "Instructor" and instructor_id != user_id:
        forbid("An Instructor may only publish availability for themselves")
    instructor = db.STORE["members"].get(instructor_id)
    if instructor is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Instructor member not found")
    if not instructor["is_instructor"]:
        raise ApiError(
            ERR_REFERENTIAL_INTEGRITY, 422,
            "instructor_id must reference a member with is_instructor true",
        )
    record = {
        "id": str(uuid.uuid4()),
        "instructor_id": instructor_id,
        "start_at": start_at,
        "end_at": end_at,
        "status": "OPEN",
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.STORE["availability"][record["id"]] = record
    return success(ser_availability(record), "object", 201)


@bp.get("/soaring/instructor-availability")
def list_windows():
    auth()
    items = list(db.STORE["availability"].values())
    instructor_id = request.args.get("instructor_id")
    if instructor_id is not None:
        items = [w for w in items if w["instructor_id"] == instructor_id]
    page, meta = paginate(sort_items(items))
    return success([ser_availability(w) for w in page], "array", 200, meta)


@bp.get("/soaring/instructor-availability/<wid>")
def get_window(wid):
    auth()
    return success(ser_availability(_get_window_or_404(wid)), "object", 200)


@bp.post("/soaring/instructor-availability/<wid>/cancel")
def cancel_window(wid):
    user_id, role = auth()
    require_role(role, ["Instructor", "ClubAdmin"])
    window = _get_window_or_404(wid)
    if role == "Instructor" and window["instructor_id"] != user_id:
        forbid("An Instructor may only cancel their own availability windows")
    if window["status"] != "OPEN":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Only an OPEN availability window can be cancelled"
        )
    window["status"] = "CANCELLED"
    touch(window)
    return success(ser_availability(window), "object", 200)
