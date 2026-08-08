"""Routes: viewing rooms and viewing bookings."""
from flask import Blueprint, request

from store import db, new_record, touch, serialize
from common import (auth, get_body, require_fields, check_enum, require_int,
                    get_or_404, fk_or_404, paginate)
from envelope import object_response, list_response
from errors import err
from timeutil import parse_dt

bp = Blueprint("viewing", __name__)

BOOKING_STATES = {"REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW"}


# ---------------------------------------------------------------------------
# Viewing rooms
# ---------------------------------------------------------------------------
@bp.route("/viewing-rooms", methods=["POST"])
def create_room():
    auth(["Coordinator"])
    body = get_body()
    require_fields(body, ["name", "capacity_persons"])
    require_int(body, "capacity_persons")
    rec = new_record({
        "name": body["name"],
        "capacity_persons": body["capacity_persons"],
        "status": "OPERATIONAL",
    })
    db["viewing_rooms"][rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/viewing-rooms/<rid>/state", methods=["POST"])
def room_state(rid):
    auth(["Coordinator"])
    rec = get_or_404("viewing_rooms", rid)
    body = get_body()
    require_fields(body, ["to_status"])
    to_status = body["to_status"]
    check_enum(to_status, {"OPERATIONAL", "CLOSED"}, "to_status")
    cur = rec["status"]
    if (cur, to_status) not in {("OPERATIONAL", "CLOSED"), ("CLOSED", "OPERATIONAL")}:
        raise err("ERR_INVALID_STATE", "cannot move room from %s to %s" % (cur, to_status))
    rec["status"] = to_status
    touch(rec)
    return object_response(serialize(rec))


@bp.route("/viewing-rooms/<rid>", methods=["GET"])
def get_room(rid):
    auth(["Coordinator", "Client"])
    rec = get_or_404("viewing_rooms", rid)
    return object_response(serialize(rec))


@bp.route("/viewing-rooms", methods=["GET"])
def list_rooms():
    auth(["Coordinator", "Client"])
    st = request.args.get("status")
    recs = [r for r in db["viewing_rooms"].values() if st is None or r["status"] == st]
    items, limit, offset, total = paginate(recs)
    return list_response(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Viewing bookings
# ---------------------------------------------------------------------------
@bp.route("/viewing-bookings", methods=["POST"])
def create_booking():
    uid, role = auth(["Client", "Coordinator"])
    body = get_body()
    # Client may book only for its own client_id (ownership, checkable pre-existence)
    if role == "Client" and body.get("client_id") is not None and body["client_id"] != uid:
        raise err("ERR_OWNERSHIP_REQUIRED", "may only book for your own client_id")
    artwork = fk_or_404("artworks", body.get("artwork_id"))
    fk_or_404("viewing_rooms", body.get("viewing_room_id"))
    fk_or_404("clients", body.get("client_id"))
    require_fields(body, ["artwork_id", "viewing_room_id", "client_id",
                          "scheduled_start", "scheduled_end"])
    if role == "Client" and artwork["client_id"] != uid:
        raise err("ERR_OWNERSHIP_REQUIRED", "may only book your own artwork")
    start = parse_dt(body["scheduled_start"])
    end = parse_dt(body["scheduled_end"])
    if not end > start:
        raise err("ERR_TIME_WINDOW_INVALID", "scheduled_end must be after scheduled_start")
    rec = new_record({
        "artwork_id": body["artwork_id"],
        "viewing_room_id": body["viewing_room_id"],
        "client_id": body["client_id"],
        "scheduled_start": body["scheduled_start"],
        "scheduled_end": body["scheduled_end"],
        "status": "REQUESTED",
    })
    db["viewing_bookings"][rec["id"]] = rec
    return object_response(serialize(rec), 201)


def _room_conflict(room_id, new_start, new_end, exclude_id):
    for b in db["viewing_bookings"].values():
        if b["id"] == exclude_id or b["viewing_room_id"] != room_id or b["status"] != "CONFIRMED":
            continue
        es = parse_dt(b["scheduled_start"])
        ee = parse_dt(b["scheduled_end"])
        # half-open overlap, no buffer
        if new_start < ee and es < new_end:
            return True
    return False


@bp.route("/viewing-bookings/<rid>/state", methods=["POST"])
def booking_state(rid):
    auth(["Coordinator"])
    rec = get_or_404("viewing_bookings", rid)
    body = get_body()
    require_fields(body, ["to_status"])
    to_status = body["to_status"]
    check_enum(to_status, BOOKING_STATES, "to_status")
    cur = rec["status"]
    valid = {("REQUESTED", "CONFIRMED"), ("CONFIRMED", "COMPLETED"),
             ("CONFIRMED", "NO_SHOW"), ("REQUESTED", "CANCELLED"), ("CONFIRMED", "CANCELLED")}
    if (cur, to_status) not in valid:
        raise err("ERR_INVALID_STATE", "cannot move booking from %s to %s" % (cur, to_status))
    if to_status == "CONFIRMED":
        artwork = db["artworks"].get(rec["artwork_id"])
        room = db["viewing_rooms"].get(rec["viewing_room_id"])
        if artwork is not None and artwork["condition_status"] == "MAJOR_DAMAGE":
            raise err("ERR_ARTWORK_CONDITION_UNSAFE", "artwork condition unsafe")
        if room is None or room["status"] != "OPERATIONAL":
            raise err("ERR_ROOM_NOT_OPERATIONAL", "viewing room is not operational")
        if _room_conflict(rec["viewing_room_id"], parse_dt(rec["scheduled_start"]),
                          parse_dt(rec["scheduled_end"]), rec["id"]):
            raise err("ERR_ROOM_UNAVAILABLE", "room already booked for an overlapping window")
    rec["status"] = to_status
    touch(rec)
    return object_response(serialize(rec))


@bp.route("/viewing-bookings/<rid>", methods=["GET"])
def get_booking(rid):
    uid, role = auth(["Coordinator", "Client"])
    rec = get_or_404("viewing_bookings", rid)
    if role == "Client" and rec["client_id"] != uid:
        raise err("ERR_OWNERSHIP_REQUIRED", "not your booking")
    return object_response(serialize(rec))


@bp.route("/viewing-bookings", methods=["GET"])
def list_bookings():
    uid, role = auth(["Coordinator", "Client"])
    aid = request.args.get("artwork_id")
    vrid = request.args.get("viewing_room_id")
    cid = request.args.get("client_id")
    st = request.args.get("status")
    if role == "Client":
        if cid is not None and cid != uid:
            raise err("ERR_OWNERSHIP_REQUIRED", "not your client scope")
        cid = uid
    recs = [r for r in db["viewing_bookings"].values()
            if (aid is None or r["artwork_id"] == aid)
            and (vrid is None or r["viewing_room_id"] == vrid)
            and (cid is None or r["client_id"] == cid)
            and (st is None or r["status"] == st)]
    items, limit, offset, total = paginate(recs)
    return list_response(items, limit, offset, total)
