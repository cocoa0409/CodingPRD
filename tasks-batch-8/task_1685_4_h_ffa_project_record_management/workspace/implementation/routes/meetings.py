"""Meetings, rooms, and attendance (PRD 3.6)."""

from flask import Blueprint, request

import clock
import db
import response
from middleware import (authenticate, resolve_caller, must_find,
                        new_common_fields, new_audit_fields, touch)
from validation import (get_body, as_str, as_enum, as_datetime_str, as_int_range,
                        pagination_params, paginate, sort_by_creation, present)
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_ROOM_CONFLICT)
from services import calc
from services.serialize import meeting_view, room_view, attendance_view

rooms_bp = Blueprint("rooms", __name__)
bp = Blueprint("meetings", __name__)
attendance_bp = Blueprint("attendance", __name__)

ALL_ROLES = ["ProgramAdmin", "Volunteer", "Member"]
ATTENDANCE_STATUSES = ("PRESENT", "ABSENT", "EXCUSED")


# --------------------------------------------------------------------------
# Rooms
# --------------------------------------------------------------------------
@rooms_bp.post("/rooms")
def create_room():
    role, user_id = authenticate(["ProgramAdmin"])
    resolve_caller(role, user_id)
    body = get_body()
    name = as_str(body, "name")
    capacity = as_int_range(body, "capacity", lo=0)
    # Room names are unique (PRD 3.6).
    for existing in db.table("rooms").values():
        if existing["name"] == name:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "A room named '%s' already exists" % name)
    rec = new_common_fields()
    rec.update({"name": name, "capacity": capacity})
    db.table("rooms")[rec["id"]] = rec
    return response.success(room_view(rec), status=201)


@rooms_bp.get("/rooms/<rid>")
def get_room(rid):
    role, user_id = authenticate(["ProgramAdmin", "Volunteer"])
    rec = must_find("rooms", rid, "Room")
    resolve_caller(role, user_id)
    return response.success(room_view(rec))


# --------------------------------------------------------------------------
# Meetings
# --------------------------------------------------------------------------
def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [starts_at, ends_at) overlap: meetings that merely touch --
    one ends exactly when the other begins -- do NOT overlap (PRD 3.6)."""
    return a_start < b_end and b_start < a_end


@bp.post("/meetings")
def create_meeting():
    role, user_id = authenticate(["Volunteer"])
    body = get_body()
    # Priority 3: referenced identifiers exist, left-to-right (club_id, room_id).
    club = None
    room = None
    if isinstance(body.get("club_id"), str):
        club = must_find("clubs", body["club_id"], "Club")
    if isinstance(body.get("room_id"), str):
        room = must_find("rooms", body["room_id"], "Room")
    resolve_caller(role, user_id)
    # Priority 8: room overlap. The new meeting's half-open interval must not
    # overlap any existing SCHEDULED or HELD meeting in the same room.
    starts_dt = clock.parse_iso(body.get("starts_at"))
    ends_dt = clock.parse_iso(body.get("ends_at"))
    if room is not None and starts_dt is not None and ends_dt is not None:
        for existing in db.table("meetings").values():
            if existing["room_id"] != room["id"]:
                continue
            if existing["status"] not in ("SCHEDULED", "HELD"):
                continue
            if _intervals_overlap(starts_dt, ends_dt,
                                  existing["_starts_at_dt"], existing["_ends_at_dt"]):
                raise ApiError(ERR_ROOM_CONFLICT, 409,
                               "Meeting interval overlaps an existing SCHEDULED/HELD meeting in the same room")
    # Priority 14: request shape -- required fields and ends_at strictly after
    # starts_at.
    club_id = present(body, "club_id")
    if not isinstance(club_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'club_id': must be a string")
    room_id = present(body, "room_id")
    if not isinstance(room_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'room_id': must be a string")
    if club is None:
        club = must_find("clubs", club_id, "Club")
    if room is None:
        room = must_find("rooms", room_id, "Room")
    starts_at = as_datetime_str(body, "starts_at")
    ends_at = as_datetime_str(body, "ends_at")
    starts_dt = clock.parse_iso(starts_at)
    ends_dt = clock.parse_iso(ends_at)
    if not ends_dt > starts_dt:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field 'ends_at': must be strictly after starts_at")
    rec = new_common_fields()
    rec.update({
        "club_id": club["id"],
        "starts_at": starts_at,
        "ends_at": ends_at,
        "_starts_at_dt": starts_dt,
        "_ends_at_dt": ends_dt,
        "room_id": room["id"],
        "status": "SCHEDULED",
    })
    db.table("meetings")[rec["id"]] = rec
    return response.success(meeting_view(rec), status=201)


@bp.get("/meetings")
def list_meetings():
    role, user_id = authenticate(ALL_ROLES)
    resolve_caller(role, user_id)
    limit, offset = pagination_params()
    items = list(db.table("meetings").values())
    room_id = request.args.get("room_id")
    if room_id is not None:
        items = [m for m in items if m["room_id"] == room_id]
    club_id = request.args.get("club_id")
    if club_id is not None:
        items = [m for m in items if m["club_id"] == club_id]
    items = sort_by_creation(items)
    page, meta = paginate(items, limit, offset)
    return response.success([meeting_view(m) for m in page],
                            response_type="array", pagination=meta)


@bp.get("/meetings/<mid>")
def get_meeting(mid):
    role, user_id = authenticate(ALL_ROLES)
    rec = must_find("meetings", mid, "Meeting")
    resolve_caller(role, user_id)
    return response.success(meeting_view(rec))


@bp.post("/meetings/<mid>/mark-held")
def mark_meeting_held(mid):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("meetings", mid, "Meeting")
    resolve_caller(role, user_id)
    if rec["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Meeting status must be SCHEDULED to mark held")
    rec["status"] = "HELD"
    touch(rec)
    # Marking held recomputes the eligibility_posture of every ACTIVE member
    # of the meeting's club, because attendance evidence has now landed.
    for member in db.table("members").values():
        if member["club_id"] == rec["club_id"] and member["enrollment_status"] == "ACTIVE":
            calc.recompute_member_posture(member)
    return response.success(meeting_view(rec))


@bp.post("/meetings/<mid>/cancel")
def cancel_meeting(mid):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("meetings", mid, "Meeting")
    resolve_caller(role, user_id)
    if rec["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Meeting status must be SCHEDULED to cancel")
    rec["status"] = "CANCELLED"
    touch(rec)
    return response.success(meeting_view(rec))


@bp.get("/meetings/<mid>/attendance")
def list_meeting_attendance(mid):
    role, user_id = authenticate(ALL_ROLES)
    meeting = must_find("meetings", mid, "Meeting")
    resolve_caller(role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation(
        [a for a in db.table("attendance").values() if a["meeting_id"] == meeting["id"]])
    page, meta = paginate(items, limit, offset)
    return response.success([attendance_view(a) for a in page],
                            response_type="array", pagination=meta)


# --------------------------------------------------------------------------
# Attendance
# --------------------------------------------------------------------------
@attendance_bp.post("/attendance")
def create_attendance():
    role, user_id = authenticate(["Volunteer"])
    body = get_body()
    # Priority 3: referenced identifiers exist (meeting_id, member_id).
    meeting = None
    member = None
    if isinstance(body.get("meeting_id"), str):
        meeting = must_find("meetings", body["meeting_id"], "Meeting")
    if isinstance(body.get("member_id"), str):
        member = must_find("members", body["member_id"], "Member")
    resolve_caller(role, user_id)
    # Priority 14: request shape.
    meeting_id = present(body, "meeting_id")
    if not isinstance(meeting_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'meeting_id': must be a string")
    member_id = present(body, "member_id")
    if not isinstance(member_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'member_id': must be a string")
    if meeting is None:
        meeting = must_find("meetings", meeting_id, "Meeting")
    if member is None:
        member = must_find("members", member_id, "Member")
    status = as_enum(body, "attendance_status", ATTENDANCE_STATUSES)
    rec = new_audit_fields()
    rec.update({
        "meeting_id": meeting["id"],
        "member_id": member["id"],
        "attendance_status": status,
    })
    db.table("attendance")[rec["id"]] = rec
    return response.success(attendance_view(rec), status=201)
