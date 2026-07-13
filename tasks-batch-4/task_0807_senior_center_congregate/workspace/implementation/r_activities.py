"""Rooms, activity sessions (half-open room overlap), and signups."""
from flask import Blueprint, request

from store import db, base_common, touch
from core import (
    require_actor, authorize, check_ownership, get_body, ok_object, ok_array,
    paginate, req_str, req_int, opt_enum, err, req_datetime, parse_dt,
)
from lookups import get_room, get_session, get_participant, get_signup
from serializers import ser_room, ser_session, ser_signup

bp = Blueprint("activities", __name__)

SESSION_CATEGORY = {"ACTIVITY", "WELLNESS"}


# --------------------------------- Room ------------------------------------
@bp.post("/rooms")
def create_room():
    actor = require_actor()
    authorize(actor, {"CenterAdmin"})
    body = get_body()
    name = req_str(body, "name")
    capacity = req_int(body, "capacity", minimum=1)
    rec = base_common(with_version=False)
    rec.update({"name": name, "capacity": capacity})
    db.rooms[rec["id"]] = rec
    return ok_object(ser_room(rec), 201)


# ----------------------------- ActivitySession -----------------------------
@bp.post("/activity-sessions")
def create_session():
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator"})
    body = get_body()
    title = req_str(body, "title")
    category = opt_enum(body, "category", SESSION_CATEGORY, "ACTIVITY")
    room_id = req_str(body, "room_id")
    starts_raw, starts = req_datetime(body, "starts_at")
    ends_raw, ends = req_datetime(body, "ends_at")
    capacity = req_int(body, "capacity", minimum=1)

    get_room(room_id)  # existence
    if not (starts < ends):
        raise err("ERR_INVALID_TIME_WINDOW", "starts_at must be before ends_at")
    # Half-open room overlap against SCHEDULED sessions in the same room.
    for s in db.sessions.values():
        if s["room_id"] != room_id or s["status"] != "SCHEDULED":
            continue
        s_start = parse_dt(s["starts_at"])
        s_end = parse_dt(s["ends_at"])
        if starts < s_end and s_start < ends:
            raise err("ERR_ROOM_DOUBLE_BOOKED", "Room already booked for this interval")

    rec = base_common()
    rec.update({
        "title": title,
        "category": category,
        "room_id": room_id,
        "starts_at": starts_raw,
        "ends_at": ends_raw,
        "capacity": capacity,
        "enrolled_count": 0,
        "status": "SCHEDULED",
    })
    db.sessions[rec["id"]] = rec
    return ok_object(ser_session(rec), 201)


@bp.get("/activity-sessions/<sid>")
def get_session_route(sid):
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator", "Participant", "Auditor"})
    return ok_object(ser_session(get_session(sid)))


@bp.get("/activity-sessions")
def list_sessions():
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator", "Participant", "Auditor"})
    rows = list(db.sessions.values())
    if "room_id" in request.args:
        rows = [r for r in rows if r["room_id"] == request.args.get("room_id")]
    window, page = paginate(rows)
    return ok_array([ser_session(r) for r in window], page)


@bp.post("/activity-sessions/<sid>/cancel")
def cancel_session(sid):
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator"})
    rec = get_session(sid)
    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Only a SCHEDULED session can be cancelled")
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok_object(ser_session(rec))


# ------------------------------ ActivitySignup -----------------------------
@bp.post("/activity-signups")
def create_signup():
    actor = require_actor()
    authorize(actor, {"Participant", "Coordinator"})
    body = get_body()
    session_id = req_str(body, "session_id")
    participant_id = req_str(body, "participant_id")
    check_ownership(actor, participant_id)

    session = get_session(session_id)
    participant = get_participant(participant_id)

    if participant["status"] != "ACTIVE":
        raise err("ERR_PARTICIPANT_INACTIVE", "Participant is not ACTIVE")
    if db.clock >= parse_dt(session["starts_at"]):
        raise err("ERR_SIGNUP_CLOSED", "Signups are closed for this session")
    if session["enrolled_count"] >= session["capacity"]:
        raise err("ERR_SESSION_FULL", "Session is full")
    for su in db.signups.values():
        if (su["session_id"] == session_id and su["participant_id"] == participant_id
                and su["status"] == "CONFIRMED"):
            raise err("ERR_DUPLICATE_SIGNUP", "Participant already signed up")

    rec = base_common()
    rec.update({
        "session_id": session_id,
        "participant_id": participant_id,
        "status": "CONFIRMED",
    })
    session["enrolled_count"] += 1
    touch(session)
    db.signups[rec["id"]] = rec
    return ok_object(ser_signup(rec), 201)


@bp.get("/activity-signups/<sid>")
def get_signup_route(sid):
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator", "Participant", "Auditor"})
    return ok_object(ser_signup(get_signup(sid)))


@bp.get("/activity-signups")
def list_signups():
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator", "Participant", "Auditor"})
    rows = list(db.signups.values())
    args = request.args
    for key in ("session_id", "participant_id"):
        if key in args:
            rows = [r for r in rows if r.get(key) == args.get(key)]
    window, page = paginate(rows)
    return ok_array([ser_signup(r) for r in window], page)


@bp.post("/activity-signups/<sid>/cancel")
def cancel_signup(sid):
    actor = require_actor()
    authorize(actor, {"Participant", "Coordinator"})
    rec = get_signup(sid)
    check_ownership(actor, rec["participant_id"])
    if rec["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Only a CONFIRMED signup can be cancelled")
    rec["status"] = "CANCELLED"
    session = db.sessions.get(rec["session_id"])
    if session is not None:
        session["enrolled_count"] -= 1
        touch(session)
    touch(rec)
    return ok_object(ser_signup(rec))
