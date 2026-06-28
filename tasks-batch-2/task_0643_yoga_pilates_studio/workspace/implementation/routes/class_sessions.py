"""ClassSession endpoints: CRUD, publish, start, complete, cancel, reservations list."""
from flask import Blueprint, request

from db import store
from errors import err
from clock import parse_iso
from middleware import authenticate, require_roles
from models import make_class_session, serialize, touch
from response import success, list_success
from helpers import (get_json_body, parse_pagination, paginate,
                     require_int, require_datetime, find_or_404)
from services import (recompute_session_counts, recompute_session_posture,
                      effective_capacity, refund_credit, raise_fee,
                      add_no_show_strike, mark_attended)
from scheduling import session_room_conflict, session_teacher_conflict

bp = Blueprint("class_sessions", __name__)

CATALOG_READERS = {"StudioManager", "Member", "Instructor"}
DISCIPLINES = {"VINYASA", "YIN", "REFORMER", "MAT_PILATES"}


@bp.post("/class-sessions")
def create_session():
    principal = authenticate()
    require_roles(principal, {"StudioManager"})
    body = get_json_body()

    room_id = body.get("room_id")
    teacher_id = body.get("teacher_id")
    if not isinstance(room_id, str) or not room_id:
        raise err("ERR_INVALID_REQUEST", "room_id is required")
    if not isinstance(teacher_id, str) or not teacher_id:
        raise err("ERR_INVALID_REQUEST", "teacher_id is required")
    # Existence (left-to-right): room then teacher.
    room = find_or_404(store.rooms, room_id, "Room")
    find_or_404(store.teachers, teacher_id, "Teacher")

    recurrence_parent_id = body.get("recurrence_parent_id")
    if recurrence_parent_id is not None:
        if not isinstance(recurrence_parent_id, str):
            raise err("ERR_INVALID_REQUEST", "recurrence_parent_id must be a string")
        find_or_404(store.class_sessions, recurrence_parent_id, "ClassSession")

    if body.get("discipline") not in DISCIPLINES:
        raise err("ERR_INVALID_REQUEST", "discipline invalid")
    discipline = body["discipline"]

    start_dt = require_datetime(body, "start_utc")
    end_dt = require_datetime(body, "end_utc")
    if end_dt <= start_dt:
        raise err("ERR_END_BEFORE_START", "end_utc must be after start_utc")

    published_capacity = require_int(body, "published_capacity", minimum=1)

    waitlist_capacity = body.get("waitlist_capacity")
    if waitlist_capacity is None:
        waitlist_capacity = 5
    else:
        if isinstance(waitlist_capacity, bool) or not isinstance(waitlist_capacity, int) \
                or waitlist_capacity < 0:
            raise err("ERR_INVALID_REQUEST", "waitlist_capacity must be an integer >= 0")

    # Capacity vs room at creation.
    if published_capacity > room["station_capacity"]:
        raise err("ERR_CAPACITY_EXCEEDS_ROOM", "published_capacity exceeds room.station_capacity")

    session = make_class_session(
        room_id, teacher_id, discipline, body["start_utc"], body["end_utc"],
        published_capacity, waitlist_capacity, recurrence_parent_id)
    store.class_sessions[session["id"]] = session
    return success(serialize(session), status=201)


@bp.get("/class-sessions/<sid>")
def get_session(sid):
    principal = authenticate()
    require_roles(principal, CATALOG_READERS)
    session = find_or_404(store.class_sessions, sid, "ClassSession")
    recompute_session_counts(session)
    return success(serialize(session))


@bp.get("/class-sessions")
def list_sessions():
    principal = authenticate()
    require_roles(principal, CATALOG_READERS)
    limit, offset = parse_pagination()
    items = list(store.class_sessions.values())
    for key in ("room_id", "teacher_id", "recurrence_parent_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [s for s in items if s.get(key) == val]
    for s in items:
        recompute_session_counts(s)
    window, total = paginate(items, limit, offset)
    return list_success([serialize(s) for s in window], 200, limit, offset, total)


@bp.post("/class-sessions/<sid>/publish")
def publish_session(sid):
    principal = authenticate()
    require_roles(principal, {"StudioManager"})
    session = find_or_404(store.class_sessions, sid, "ClassSession")

    # State validity.
    if session["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Session is not SCHEDULED")

    room = store.rooms.get(session["room_id"])
    teacher = store.teachers.get(session["teacher_id"])

    # Room must be OPEN.
    if room is None or room["status"] != "OPEN":
        raise err("ERR_ROOM_CLOSED", "Hosting room is not OPEN")

    # Teacher certified + active.
    if teacher is None or teacher["status"] != "ACTIVE" \
            or session["discipline"] not in teacher["certifications"]:
        raise err("ERR_TEACHER_NOT_CERTIFIED", "Teacher not certified/active for discipline")

    # Room overlap.
    if session_room_conflict(session):
        raise err("ERR_ROOM_DOUBLE_BOOKED", "Room is double-booked")

    # Teacher overlap.
    if session_teacher_conflict(session):
        raise err("ERR_TEACHER_DOUBLE_BOOKED", "Teacher is double-booked")

    # Capacity vs room at publish.
    if session["published_capacity"] > room["station_capacity"]:
        raise err("ERR_CAPACITY_EXCEEDS_ROOM", "published_capacity exceeds room.station_capacity")

    session["status"] = "OPEN"
    touch(session)
    return success(serialize(session))


@bp.post("/class-sessions/<sid>/start")
def start_session(sid):
    principal = authenticate()
    require_roles(principal, {"StudioManager"})
    session = find_or_404(store.class_sessions, sid, "ClassSession")
    if session["status"] not in ("OPEN", "FULL"):
        raise err("ERR_INVALID_STATE", "Session is not OPEN/FULL")
    if store.clock.now() < parse_iso(session["start_utc"]):
        raise err("ERR_INVALID_STATE", "Logical clock has not reached start_utc")
    session["status"] = "IN_PROGRESS"
    touch(session)
    return success(serialize(session))


@bp.post("/class-sessions/<sid>/complete")
def complete_session(sid):
    principal = authenticate()
    require_roles(principal, {"StudioManager"})
    session = find_or_404(store.class_sessions, sid, "ClassSession")
    if session["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Session is not IN_PROGRESS")

    reservations = [r for r in store.reservations.values()
                    if r["class_session_id"] == sid]
    # Deterministic settlement order: by creation sequence.
    reservations.sort(key=lambda r: r["_seq"])

    for res in reservations:
        if res["status"] == "CHECKED_IN":
            res["status"] = "ATTENDED"
            touch(res)
            member = store.members.get(res["member_id"])
            if member is not None:
                mark_attended(member)
        elif res["status"] == "BOOKED":
            res["status"] = "NO_SHOW"
            touch(res)
            member = store.members.get(res["member_id"])
            if member is not None:
                # Fee assessed with strikes read BEFORE increment, then strike +1.
                raise_fee(member, res, "NO_SHOW")
                add_no_show_strike(member)
            # held credit forfeited (not refunded)
        elif res["status"] == "WAITLISTED":
            # Held credit returned exactly as in a waitlisted early cancel.
            res["status"] = "CANCELLED_EARLY"
            if res["credit_charged"]:
                ent = store.entitlements.get(res["entitlement_id"])
                if ent is not None:
                    refund_credit(ent)
                res["credit_charged"] = False
            res["waitlist_position"] = None
            touch(res)

    session["status"] = "COMPLETED"
    recompute_session_counts(session)
    touch(session)
    return success(serialize(session))


@bp.post("/class-sessions/<sid>/cancel")
def cancel_session(sid):
    principal = authenticate()
    require_roles(principal, {"StudioManager"})
    session = find_or_404(store.class_sessions, sid, "ClassSession")
    if session["status"] not in ("SCHEDULED", "OPEN", "FULL"):
        raise err("ERR_INVALID_STATE", "Session cannot be cancelled from its current state")

    reservations = [r for r in store.reservations.values()
                    if r["class_session_id"] == sid]
    reservations.sort(key=lambda r: r["_seq"])

    for res in reservations:
        if res["status"] in ("BOOKED", "WAITLISTED", "CHECKED_IN"):
            had_credit = res["credit_charged"]
            res["status"] = "CANCELLED_EARLY"
            res["waitlist_position"] = None
            if had_credit:
                ent = store.entitlements.get(res["entitlement_id"])
                if ent is not None:
                    # Studio cancellation: final variant returns the credit to the
                    # entitlement (credits_used -= 1). Cash valuation per §3.7 is the
                    # per-credit cash value; the credit itself is restored.
                    refund_credit(ent)
                res["credit_charged"] = False
            touch(res)

    session["status"] = "CANCELLED"
    recompute_session_counts(session)
    touch(session)
    return success(serialize(session))


@bp.get("/class-sessions/<sid>/reservations")
def session_reservations_list(sid):
    principal = authenticate()
    require_roles(principal, CATALOG_READERS)
    find_or_404(store.class_sessions, sid, "ClassSession")
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [r for r in store.reservations.values() if r["class_session_id"] == sid]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    window, total = paginate(items, limit, offset)
    return list_success([serialize(r) for r in window], 200, limit, offset, total)
