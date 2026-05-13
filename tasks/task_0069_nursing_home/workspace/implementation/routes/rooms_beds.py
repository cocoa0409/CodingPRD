"""Rooms and beds endpoints."""
from flask import request

from db import LOCK, get_db
from errors import APIError
from helpers import (check_occ, new_entity, paginate, parse_pagination,
                     require_body, require_enum, require_field, touch)
from middleware import require_roles
from response import list_success, success
from services import waitlist as waitlist_svc


ROOM_TYPE = {"STANDARD", "INTENSIVE_CARE"}
BED_TYPE = {"SINGLE", "DOUBLE", "MULTI", "INTENSIVE_CARE"}


def _serialize_room(r):
    return dict(r)


def _serialize_bed(b):
    return dict(b)


def register(app):

    # POST /rooms
    @app.post("/rooms")
    @require_roles("Admin")
    def create_room(user_id, role):
        body = require_body()
        room_number = require_field(body, "room_number", str)
        floor = require_field(body, "floor", int)
        room_type = require_enum(body, "room_type", ROOM_TYPE)
        if floor < 1:
            raise APIError("ERR_VALIDATION", "floor must be >= 1", 422)
        with LOCK:
            db = get_db()
            for r in db.rooms.values():
                if r["room_number"] == room_number:
                    raise APIError("ERR_VALIDATION", "room_number must be unique", 422)
            room = new_entity({
                "room_number": room_number,
                "floor": floor,
                "room_type": room_type,
            })
            db.rooms[room["id"]] = room
            return success(_serialize_room(room), status=201)

    # GET /rooms
    @app.get("/rooms")
    @require_roles("Admin", "Supervisor")
    def list_rooms(user_id, role):
        limit, offset = parse_pagination()
        db = get_db()
        items = sorted(db.rooms.values(), key=lambda r: r["created_at"])
        page, total = paginate(items, limit, offset)
        return list_success([_serialize_room(r) for r in page], limit, offset, total)

    # POST /rooms/{id}/beds
    @app.post("/rooms/<rid>/beds")
    @require_roles("Admin")
    def create_bed(user_id, role, rid):
        body = require_body()
        bed_code = require_field(body, "bed_code", str)
        bed_type = require_enum(body, "bed_type", BED_TYPE)
        monthly_fee = require_field(body, "monthly_bed_fee_cents", int)
        if monthly_fee < 0:
            raise APIError("ERR_VALIDATION", "monthly_bed_fee_cents must be >=0", 422)
        with LOCK:
            db = get_db()
            room = db.rooms.get(rid)
            if room is None:
                raise APIError("ERR_NOT_FOUND", f"Room {rid} not found", 404)
            # bed_code uniqueness within the room
            for b in db.beds.values():
                if b["room_id"] == rid and b["bed_code"] == bed_code:
                    raise APIError("ERR_VALIDATION", "bed_code must be unique within room", 422)
            bed = new_entity({
                "room_id": rid,
                "bed_code": bed_code,
                "bed_type": bed_type,
                "monthly_bed_fee_cents": monthly_fee,
                "status": "AVAILABLE",
                "current_elder_id": None,
            })
            db.beds[bed["id"]] = bed
            # Newly-available bed triggers waitlist promotion
            waitlist_svc.promote_for_bed(bed)
            return success(_serialize_bed(bed), status=201)

    # GET /beds
    @app.get("/beds")
    @require_roles("Admin", "Supervisor")
    def list_beds(user_id, role):
        limit, offset = parse_pagination()
        status_f = request.args.get("status")
        type_f = request.args.get("bed_type")
        db = get_db()
        items = list(db.beds.values())
        if status_f:
            items = [b for b in items if b["status"] == status_f]
        if type_f:
            items = [b for b in items if b["bed_type"] == type_f]
        items.sort(key=lambda b: b["created_at"])
        page, total = paginate(items, limit, offset)
        return list_success([_serialize_bed(b) for b in page], limit, offset, total)

    # POST /beds/{id}/maintenance
    @app.post("/beds/<bid>/maintenance")
    @require_roles("Admin")
    def bed_maintenance(user_id, role, bid):
        with LOCK:
            db = get_db()
            bed = db.beds.get(bid)
            if bed is None:
                raise APIError("ERR_NOT_FOUND", f"Bed {bid} not found", 404)
            if bed["status"] != "AVAILABLE":
                raise APIError("ERR_INVALID_STATE",
                               f"Bed is {bed['status']}, only AVAILABLE -> MAINTENANCE", 409)
            bed["status"] = "MAINTENANCE"
            touch(bed)
            return success(_serialize_bed(bed))

    # POST /beds/{id}/maintenance-complete
    @app.post("/beds/<bid>/maintenance-complete")
    @require_roles("Admin")
    def bed_maintenance_complete(user_id, role, bid):
        with LOCK:
            db = get_db()
            bed = db.beds.get(bid)
            if bed is None:
                raise APIError("ERR_NOT_FOUND", f"Bed {bid} not found", 404)
            if bed["status"] != "MAINTENANCE":
                raise APIError("ERR_INVALID_STATE",
                               f"Bed is {bed['status']}, expected MAINTENANCE", 409)
            bed["status"] = "AVAILABLE"
            touch(bed)
            waitlist_svc.promote_for_bed(bed)
            return success(_serialize_bed(bed))
