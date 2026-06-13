"""PacketPickup endpoints + transitions."""
from flask import Blueprint, request

from db import db, new_id
from errors import (err, ERR_INVALID_STATE, ERR_PACKET_ALREADY_ISSUED,
                    ERR_PACKET_NOT_ELIGIBLE, ERR_NOT_FOUND)
from middleware import auth, require_role, get_json
from response import object_response
from services.store import stamp_new, serialize_generic, touch, paginate_and_respond
from services.validate import require_str, opt_bool, lookup

bp = Blueprint("packets", __name__)


@bp.route("/packet-pickups", methods=["POST"])
def create_pickup():
    user_id, role = auth()
    require_role(role, {"PacketStaff"})
    body = get_json()
    registration_id = require_str(body, "registration_id")
    reg = db.registrations.get(registration_id)
    if reg is None:
        raise err(ERR_NOT_FOUND, "Registration not found")
    picked_up_by = require_str(body, "picked_up_by_name")
    id_verified = opt_bool(body, "id_verified", default=False)

    # eligibility: registration CONFIRMED or BIB_ASSIGNED
    if reg["status"] not in ("CONFIRMED", "BIB_ASSIGNED"):
        raise err(ERR_PACKET_NOT_ELIGIBLE, "Registration is not eligible for packet pickup")

    # at most one ISSUED pickup at a time
    for p in db.packet_pickups.values():
        if p["registration_id"] == registration_id and p["status"] == "ISSUED":
            raise err(ERR_PACKET_ALREADY_ISSUED, "Registration already holds an ISSUED packet")

    pid = new_id()
    p = {
        "id": pid,
        "registration_id": registration_id,
        "picked_up_by_name": picked_up_by,
        "id_verified": id_verified,
        "status": "ISSUED",
    }
    stamp_new(p)
    db.packet_pickups[pid] = p
    return object_response(serialize_generic(p), 201)


@bp.route("/packet-pickups/<pickup_id>", methods=["GET"])
def get_pickup(pickup_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant", "PacketStaff"})
    p = lookup(db.packet_pickups, pickup_id, "PacketPickup")
    return object_response(serialize_generic(p), 200)


@bp.route("/packet-pickups", methods=["GET"])
def list_pickups():
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant", "PacketStaff"})
    items = list(db.packet_pickups.values())
    for f in ("registration_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [p for p in items if p.get(f) == v]
    return paginate_and_respond("pickup", items, request.args)


@bp.route("/packet-pickups/<pickup_id>/void", methods=["POST"])
def void_pickup(pickup_id):
    user_id, role = auth()
    require_role(role, {"PacketStaff"})
    p = lookup(db.packet_pickups, pickup_id, "PacketPickup")
    if p["status"] != "ISSUED":
        raise err(ERR_INVALID_STATE, "Packet pickup must be ISSUED to void")
    p["status"] = "VOIDED"
    touch(p)
    return object_response(serialize_generic(p), 200)
