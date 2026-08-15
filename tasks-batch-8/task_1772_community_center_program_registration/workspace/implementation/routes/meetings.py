"""ClassMeeting endpoints (PRD 3.2)."""
from flask import Blueprint, request

import services
import store
from auth import ALL_ROLES, authenticate, authorize
from errors import raise_err
from util import (
    body_json,
    bump,
    get_or_404,
    list_response,
    new_record,
    opt_datetime,
    opt_str,
    req_datetime,
    req_str,
    serialize,
    success_object,
)

bp = Blueprint("meetings", __name__)

FIELDS = [
    "id",
    "session_id",
    "room_id",
    "starts_at",
    "ends_at",
    "created_at",
    "updated_at",
    "version",
]


def meeting_out(rec):
    return serialize(rec, FIELDS)


@bp.route("/class-meetings", methods=["POST"])
def create_meeting():
    _, role = authenticate()
    authorize(role, ["ProgramCoordinator"])
    body = body_json()
    session_id = req_str(body, "session_id")
    room_id = req_str(body, "room_id")
    starts_at = req_datetime(body, "starts_at")
    ends_at = req_datetime(body, "ends_at")
    if ends_at <= starts_at:
        raise_err("ERR_INVALID_REQUEST", "ends_at must be later than starts_at")
    session = get_or_404(store.sessions, session_id, "ClassSession")
    room = get_or_404(store.rooms, room_id, "Room")
    season = services.season_of_session(session)
    if season is not None and season["status"] == "CLOSED":
        raise_err("ERR_SEASON_CLOSED", "Season is CLOSED; new catalog content is rejected")
    services.check_scheduling(session, room, starts_at, ends_at)
    rec = new_record()
    rec.update(session_id=session_id, room_id=room_id, starts_at=starts_at, ends_at=ends_at)
    store.meetings[rec["id"]] = rec
    return success_object(meeting_out(rec), 201)


@bp.route("/class-meetings", methods=["GET"])
def list_meetings():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    session_id = request.args.get("session_id")
    room_id = request.args.get("room_id")
    records = list(store.meetings.values())
    if session_id is not None:
        records = [r for r in records if r["session_id"] == session_id]
    if room_id is not None:
        records = [r for r in records if r["room_id"] == room_id]
    return list_response(records, meeting_out)


@bp.route("/class-meetings/<meeting_id>", methods=["GET"])
def get_meeting(meeting_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.meetings, meeting_id, "ClassMeeting")
    return success_object(meeting_out(rec), 200)


@bp.route("/class-meetings/<meeting_id>", methods=["PATCH"])
def patch_meeting(meeting_id):
    _, role = authenticate()
    authorize(role, ["ProgramCoordinator"])
    body = body_json()
    room_id = opt_str(body, "room_id")
    starts_at = opt_datetime(body, "starts_at")
    ends_at = opt_datetime(body, "ends_at")
    if starts_at is not None and ends_at is not None and ends_at <= starts_at:
        raise_err("ERR_INVALID_REQUEST", "ends_at must be later than starts_at")
    rec = get_or_404(store.meetings, meeting_id, "ClassMeeting")
    new_room_id = room_id if room_id is not None else rec["room_id"]
    room = get_or_404(store.rooms, new_room_id, "Room")
    new_starts = starts_at if starts_at is not None else rec["starts_at"]
    new_ends = ends_at if ends_at is not None else rec["ends_at"]
    if new_ends <= new_starts:
        raise_err("ERR_INVALID_REQUEST", "ends_at must be later than starts_at")
    session = get_or_404(store.sessions, rec["session_id"], "ClassSession")
    if session["status"] not in ("DRAFT", "PUBLISHED"):
        raise_err("ERR_INVALID_STATE", "Meetings may be changed only while the session is DRAFT or PUBLISHED")
    # Re-run all checks with the new values, excluding the meeting itself.
    services.check_scheduling(session, room, new_starts, new_ends, exclude_meeting_id=rec["id"])
    rec["room_id"] = new_room_id
    rec["starts_at"] = new_starts
    rec["ends_at"] = new_ends
    bump(rec)
    return success_object(meeting_out(rec), 200)
