import random

from flask import Blueprint, request

from core import (
    db, base_entity, touch, serialize, ok_object, ok_array, paginate,
    auth, forbid, lookup, get_body, require_str, opt_str, require_enum,
    require_int, require_dt, ApiError,
)
from logic import revoke_active_decal

bp = Blueprint("vehicle", __name__)

DECAL_TIERS = {"RESIDENT", "TENANT", "TEMPORARY"}
VEHICLE_STATES = {"ACTIVE", "INACTIVE"}
DECAL_STATES = {"ACTIVE", "REVOKED", "EXPIRED"}


# ---------------------------------------------------------------------------
# Vehicles (PRD 3.2)
# ---------------------------------------------------------------------------
@bp.route("/access/vehicles", methods=["POST"])
def create_vehicle():
    uid, role = auth({"Resident", "CommunityAdmin"})
    body = get_body()
    resident_id = require_str(body, "resident_id")
    if role == "Resident" and resident_id != uid:
        forbid("Resident may only register own vehicle")
    plate = require_str(body, "plate")
    plate_state = require_str(body, "plate_state")
    make = opt_str(body, "make", None)
    model = opt_str(body, "model", None)
    color = opt_str(body, "color", None)
    lookup(db.residents, resident_id, "ERR_RESIDENT_NOT_FOUND")

    obj = base_entity()
    obj.update({
        "resident_id": resident_id,
        "plate": plate,
        "plate_state": plate_state,
        "make": make,
        "model": model,
        "color": color,
        "status": "ACTIVE",
    })
    db.vehicles[obj["id"]] = obj
    return ok_object(serialize(obj), 201)


@bp.route("/access/vehicles/<vehicle_id>", methods=["GET"])
def get_vehicle(vehicle_id):
    uid, role = auth({"CommunityAdmin", "SecurityOfficer", "Resident"})
    obj = lookup(db.vehicles, vehicle_id, "ERR_VEHICLE_NOT_FOUND")
    if role == "Resident" and obj["resident_id"] != uid:
        forbid("Resident may only read own vehicle")
    return ok_object(serialize(obj))


@bp.route("/access/vehicles", methods=["GET"])
def list_vehicles():
    uid, role = auth({"CommunityAdmin", "SecurityOfficer", "Resident"})
    args = request.args
    rows = list(db.vehicles.values())
    if role == "Resident":
        rows = [r for r in rows if r["resident_id"] == uid]
    if args.get("resident_id"):
        rows = [r for r in rows if r["resident_id"] == args["resident_id"]]
    if args.get("status"):
        rows = [r for r in rows if r["status"] == args["status"]]
    items, limit, offset, total = paginate(rows)
    return ok_array(items, limit, offset, total)


@bp.route("/access/vehicles/<vehicle_id>/transition", methods=["POST"])
def transition_vehicle(vehicle_id):
    auth({"CommunityAdmin"})
    vehicle = lookup(db.vehicles, vehicle_id, "ERR_VEHICLE_NOT_FOUND")
    body = get_body()
    to_status = require_enum(body, "to_status", VEHICLE_STATES)
    cur = vehicle["status"]
    allowed = {"ACTIVE": {"INACTIVE"}, "INACTIVE": {"ACTIVE"}}
    if to_status not in allowed.get(cur, set()):
        raise ApiError("ERR_INVALID_STATE", 409, "Transition not permitted")
    vehicle["status"] = to_status
    touch(vehicle)
    if to_status == "INACTIVE":
        revoke_active_decal(vehicle["id"])
    return ok_object(serialize(vehicle))


# ---------------------------------------------------------------------------
# Decals (PRD 3.2, OCC per 2.6)
# ---------------------------------------------------------------------------
@bp.route("/access/decals", methods=["POST"])
def create_decal():
    auth({"CommunityAdmin", "SecurityOfficer"})
    body = get_body()
    vehicle_id = require_str(body, "vehicle_id")
    vehicle = lookup(db.vehicles, vehicle_id, "ERR_VEHICLE_NOT_FOUND")
    tier = require_enum(body, "tier", DECAL_TIERS)
    valid_from = require_dt(body, "valid_from")
    valid_until = require_dt(body, "valid_until")
    expected_vehicle_version = require_int(body, "expected_vehicle_version")

    # OCC (priority before the ACTIVE-vehicle eligibility gate)
    if expected_vehicle_version != vehicle["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale vehicle version")
    if vehicle["status"] != "ACTIVE":
        raise ApiError("ERR_VEHICLE_INACTIVE", 409, "Vehicle is not ACTIVE")

    # Supersede prior ACTIVE decal(s) of this vehicle.
    for d in db.decals.values():
        if d["vehicle_id"] == vehicle_id and d["status"] == "ACTIVE":
            d["status"] = "REVOKED"
            touch(d)

    obj = base_entity()
    obj.update({
        "vehicle_id": vehicle_id,
        "tier": tier,
        "decal_number": "DCL-" + "".join(random.choices("0123456789", k=8)),
        "valid_from": valid_from,
        "valid_until": valid_until,
        "status": "ACTIVE",
    })
    db.decals[obj["id"]] = obj

    # New decal supersede increments the vehicle version by one.
    touch(vehicle)
    return ok_object(serialize(obj), 201)


@bp.route("/access/decals/<decal_id>", methods=["GET"])
def get_decal(decal_id):
    auth({"CommunityAdmin", "SecurityOfficer", "Resident"})
    obj = lookup(db.decals, decal_id, "ERR_DECAL_NOT_FOUND")
    return ok_object(serialize(obj))


@bp.route("/access/decals", methods=["GET"])
def list_decals():
    auth({"CommunityAdmin", "SecurityOfficer", "Resident"})
    args = request.args
    rows = list(db.decals.values())
    if args.get("vehicle_id"):
        rows = [r for r in rows if r["vehicle_id"] == args["vehicle_id"]]
    if args.get("status"):
        rows = [r for r in rows if r["status"] == args["status"]]
    items, limit, offset, total = paginate(rows)
    return ok_array(items, limit, offset, total)


@bp.route("/access/decals/<decal_id>/transition", methods=["POST"])
def transition_decal(decal_id):
    auth({"CommunityAdmin", "SecurityOfficer"})
    decal = lookup(db.decals, decal_id, "ERR_DECAL_NOT_FOUND")
    body = get_body()
    to_status = require_enum(body, "to_status", DECAL_STATES)
    if not (decal["status"] == "ACTIVE" and to_status == "REVOKED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Transition not permitted")
    decal["status"] = "REVOKED"
    touch(decal)
    return ok_object(serialize(decal))
