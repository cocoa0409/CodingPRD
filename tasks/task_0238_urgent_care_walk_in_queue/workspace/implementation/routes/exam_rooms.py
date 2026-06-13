"""ExamRoom endpoints (PRD §3.9)."""
from flask import Blueprint, request

import serialize
from db import db, stamp_create, touch
from errors import err
from middleware import authorize
from response import ok_object, ok_array
from validation import get_json_body, parse_pagination, paginate, require_str
from routes.lookup import get_path
from services import compute

bp = Blueprint("exam_rooms", __name__)

READ_ROLES = ["ClinicManager", "FrontDeskClerk", "TriageNurse", "Provider"]
ROOM_TYPES = {"STANDARD", "ISOLATION", "PROCEDURE"}


@bp.route("/clinics/<cid>/exam-rooms", methods=["POST"])
def create_exam_room(cid):
    authorize(["ClinicManager"])
    clinic = get_path("clinic", cid)
    body = get_json_body()
    require_str(body, "room_label")
    room_type = body.get("room_type", "STANDARD")
    if room_type not in ROOM_TYPES:
        raise err("ERR_INVALID_REQUEST", "invalid room_type")

    room = stamp_create({
        "clinic_id": clinic["id"],
        "room_label": body["room_label"],
        "room_type": room_type,
        "status": "AVAILABLE",
        "current_visit_id": None,
    })
    db.exam_rooms[room["id"]] = room
    return ok_object(serialize.exam_room(room), 201)


@bp.route("/clinics/<cid>/exam-rooms", methods=["GET"])
def list_clinic_exam_rooms(cid):
    authorize(READ_ROLES)
    clinic = get_path("clinic", cid)
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = [r for r in db.exam_rooms.values() if r["clinic_id"] == clinic["id"]]
    if status_filter is not None:
        items = [r for r in items if r["status"] == status_filter]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    page = paginate(items, limit, offset)
    return ok_array([serialize.exam_room(r) for r in page], limit, offset, len(items))


@bp.route("/exam-rooms/<rid>", methods=["GET"])
def get_exam_room(rid):
    authorize(READ_ROLES)
    room = get_path("exam_room", rid)
    return ok_object(serialize.exam_room(room))


@bp.route("/exam-rooms", methods=["GET"])
def list_exam_rooms():
    authorize(READ_ROLES)
    limit, offset = parse_pagination()
    cvid = request.args.get("current_visit_id")
    status_filter = request.args.get("status")
    items = list(db.exam_rooms.values())
    if cvid is not None:
        items = [r for r in items if r["current_visit_id"] == cvid]
    if status_filter is not None:
        items = [r for r in items if r["status"] == status_filter]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    page = paginate(items, limit, offset)
    return ok_array([serialize.exam_room(r) for r in page], limit, offset, len(items))


def _room_action(cid, rid, from_status, to_status, recompute_occupied):
    authorize(["ClinicManager"])
    clinic = get_path("clinic", cid)
    room = get_path("exam_room", rid)
    if room["clinic_id"] != clinic["id"]:
        raise err("ERR_NOT_FOUND", "room not under clinic")
    if room["status"] != from_status:
        raise err("ERR_INVALID_STATE", "room not in %s" % from_status)
    room["status"] = to_status
    touch(room)
    if recompute_occupied:
        compute.recompute_clinic(clinic)
    return ok_object(serialize.exam_room(room))


@bp.route("/clinics/<cid>/exam-rooms/<rid>/mark-clean", methods=["POST"])
def mark_clean(cid, rid):
    return _room_action(cid, rid, "CLEANING", "AVAILABLE", recompute_occupied=True)


@bp.route("/clinics/<cid>/exam-rooms/<rid>/take-offline", methods=["POST"])
def take_offline(cid, rid):
    return _room_action(cid, rid, "AVAILABLE", "OUT_OF_SERVICE", recompute_occupied=False)


@bp.route("/clinics/<cid>/exam-rooms/<rid>/return-online", methods=["POST"])
def return_online(cid, rid):
    return _room_action(cid, rid, "OUT_OF_SERVICE", "AVAILABLE", recompute_occupied=False)
