"""Workshop endpoints: CRUD, publish, close, cancel, enrollments list."""
from flask import Blueprint, request

from db import store
from errors import err
from clock import parse_iso
from middleware import authenticate, require_roles
from models import make_workshop, serialize, touch
from response import success, list_success
from helpers import (get_json_body, parse_pagination, paginate,
                     require_str, require_int, require_datetime, find_or_404)
from scheduling import workshop_room_conflict, workshop_teacher_conflict
from enroll_service import recompute_workshop_count, recompute_workshop_posture

bp = Blueprint("workshops", __name__)

CATALOG_READERS = {"StudioManager", "Member", "Instructor"}
KINDS = {"WORKSHOP", "TEACHER_TRAINING"}


@bp.post("/workshops")
def create_workshop():
    principal = authenticate()
    require_roles(principal, {"StudioManager"})
    body = get_json_body()

    room_id = body.get("room_id")
    lead_teacher_id = body.get("lead_teacher_id")
    if not isinstance(room_id, str) or not room_id:
        raise err("ERR_INVALID_REQUEST", "room_id is required")
    if not isinstance(lead_teacher_id, str) or not lead_teacher_id:
        raise err("ERR_INVALID_REQUEST", "lead_teacher_id is required")
    find_or_404(store.rooms, room_id, "Room")
    find_or_404(store.teachers, lead_teacher_id, "Teacher")

    title = require_str(body, "title")
    if body.get("kind") not in KINDS:
        raise err("ERR_INVALID_REQUEST", "kind must be WORKSHOP or TEACHER_TRAINING")
    kind = body["kind"]

    start_dt = require_datetime(body, "start_utc")
    end_dt = require_datetime(body, "end_utc")
    if end_dt <= start_dt:
        raise err("ERR_END_BEFORE_START", "end_utc must be after start_utc")

    seat_capacity = require_int(body, "seat_capacity", minimum=1)
    deposit_cents = require_int(body, "deposit_cents", minimum=0)
    price_cents = require_int(body, "price_cents", minimum=0)

    workshop = make_workshop(room_id, lead_teacher_id, title, kind,
                             body["start_utc"], body["end_utc"],
                             seat_capacity, deposit_cents, price_cents)
    store.workshops[workshop["id"]] = workshop
    return success(serialize(workshop), status=201)


@bp.get("/workshops/<wid>")
def get_workshop(wid):
    principal = authenticate()
    require_roles(principal, CATALOG_READERS)
    workshop = find_or_404(store.workshops, wid, "Workshop")
    recompute_workshop_count(workshop)
    return success(serialize(workshop))


@bp.get("/workshops")
def list_workshops():
    principal = authenticate()
    require_roles(principal, CATALOG_READERS)
    limit, offset = parse_pagination()
    items = list(store.workshops.values())
    for key in ("room_id", "lead_teacher_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [w for w in items if w.get(key) == val]
    for w in items:
        recompute_workshop_count(w)
    window, total = paginate(items, limit, offset)
    return list_success([serialize(w) for w in window], 200, limit, offset, total)


@bp.post("/workshops/<wid>/publish")
def publish_workshop(wid):
    principal = authenticate()
    require_roles(principal, {"StudioManager"})
    workshop = find_or_404(store.workshops, wid, "Workshop")
    if workshop["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Workshop is not DRAFT")

    room = store.rooms.get(workshop["room_id"])
    teacher = store.teachers.get(workshop["lead_teacher_id"])
    if room is None or room["status"] != "OPEN":
        raise err("ERR_ROOM_CLOSED", "Hosting room is not OPEN")
    if teacher is None or teacher["status"] != "ACTIVE":
        raise err("ERR_TEACHER_NOT_CERTIFIED", "Lead teacher is not ACTIVE")

    if workshop_room_conflict(workshop):
        raise err("ERR_ROOM_DOUBLE_BOOKED", "Room is double-booked (buffer-inclusive)")
    if workshop_teacher_conflict(workshop):
        raise err("ERR_TEACHER_DOUBLE_BOOKED", "Lead teacher is double-booked")

    if workshop["seat_capacity"] > room["station_capacity"]:
        raise err("ERR_CAPACITY_EXCEEDS_ROOM", "seat_capacity exceeds room.station_capacity")

    workshop["status"] = "OPEN"
    touch(workshop)
    return success(serialize(workshop))


@bp.post("/workshops/<wid>/close")
def close_workshop(wid):
    principal = authenticate()
    require_roles(principal, {"StudioManager"})
    workshop = find_or_404(store.workshops, wid, "Workshop")
    if workshop["status"] not in ("OPEN", "FULL"):
        raise err("ERR_INVALID_STATE", "Workshop is not OPEN/FULL")
    if store.clock.now() < parse_iso(workshop["end_utc"]):
        raise err("ERR_INVALID_STATE", "Logical clock has not reached end_utc")

    enrollments = [e for e in store.enrollments.values()
                   if e["workshop_id"] == wid]
    enrollments.sort(key=lambda e: e["_seq"])
    for e in enrollments:
        if e["status"] in ("APPLIED", "WAITLISTED"):
            e["status"] = "WITHDRAWN"
            touch(e)

    workshop["status"] = "CLOSED"
    touch(workshop)
    return success(serialize(workshop))


@bp.post("/workshops/<wid>/cancel")
def cancel_workshop(wid):
    principal = authenticate()
    require_roles(principal, {"StudioManager"})
    workshop = find_or_404(store.workshops, wid, "Workshop")
    if workshop["status"] not in ("DRAFT", "OPEN", "FULL"):
        raise err("ERR_INVALID_STATE", "Workshop cannot be cancelled from its current state")

    enrollments = [e for e in store.enrollments.values()
                   if e["workshop_id"] == wid]
    enrollments.sort(key=lambda e: e["_seq"])
    for e in enrollments:
        if e["status"] == "CONFIRMED":
            # Refund deposit to the member.
            member = store.members.get(e["member_id"])
            refund = e["deposit_paid_cents"]
            e["status"] = "CANCELLED_BY_STUDIO"
            e["deposit_paid_cents"] = 0
            e["balance_due_cents"] = 0
            touch(e)
            # Deposit refunded to member; outstanding_fee_cents unaffected.
            # (No member field tracks deposits; refund is reflected by zeroing.)
            _ = (member, refund)
        elif e["status"] in ("APPLIED", "WAITLISTED"):
            e["status"] = "CANCELLED_BY_STUDIO"
            touch(e)

    workshop["status"] = "CANCELLED"
    recompute_workshop_count(workshop)
    touch(workshop)
    return success(serialize(workshop))


@bp.get("/workshops/<wid>/enrollments")
def workshop_enrollments(wid):
    principal = authenticate()
    require_roles(principal, CATALOG_READERS)
    find_or_404(store.workshops, wid, "Workshop")
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [e for e in store.enrollments.values() if e["workshop_id"] == wid]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    window, total = paginate(items, limit, offset)
    return list_success([serialize(e) for e in window], 200, limit, offset, total)
