"""Vehicle routes (PRD 3.4). CarrierManager-owned writes."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import (
    body_json,
    ctx,
    list_response,
    need_int,
    need_str,
    opt_bool,
    ownership_guard,
    require_role,
)
from response import ok
from services.sweep import close_subscription

bp = Blueprint("vehicles", __name__)

SERVICE_STATUSES = ("IN_SERVICE", "OUT_OF_SERVICE", "RETIRED")
_LEGAL_SERVICE = {
    ("IN_SERVICE", "OUT_OF_SERVICE"),
    ("OUT_OF_SERVICE", "IN_SERVICE"),
    ("IN_SERVICE", "RETIRED"),
    ("OUT_OF_SERVICE", "RETIRED"),
}


@bp.post("/api/vehicles")
def create_vehicle():
    uid, role = ctx()
    require_role(role, ("CarrierManager",))
    body = body_json()
    # Rung 3: ownership comparison on the body's carrier_id is direct
    cid = body.get("carrier_id")
    if isinstance(cid, str) and cid != uid:
        ownership_guard(cid, uid)
    # Rung 4: carrier existence
    carrier = store.carriers.get(cid) if isinstance(cid, str) else None
    if isinstance(cid, str) and carrier is None:
        raise ApiError("ERR_CARRIER_NOT_FOUND", 404, "carrier id does not exist")
    # Rung 7: child writes require an ACTIVE carrier
    if carrier is not None and carrier["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CARRIER_NOT_ACTIVE", 409, "carrier must be ACTIVE to register vehicles"
        )
    # Rung 12: fields
    cid = need_str(body, "carrier_id")
    vin = need_str(body, "vin")
    plate_number = need_str(body, "plate_number")
    plate_state = need_str(body, "plate_state")
    home_state = need_str(body, "home_state_code")
    gvwr = need_int(body, "gvwr_lbs")
    if gvwr <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "gvwr_lbs must be > 0")
    hazmat = opt_bool(body, "hazmat_endorsed", False)
    # Rung 13: vin uniqueness
    for v in store.vehicles.values():
        if v["vin"] == vin:
            raise ApiError("ERR_DUPLICATE_VIN", 409, "vin already registered")
    rec = {
        "id": db.new_id(),
        "_seq": store.next_seq(),
        "carrier_id": cid,
        "vin": vin,
        "plate_number": plate_number,
        "plate_state": plate_state,
        "home_state_code": home_state,
        "gvwr_lbs": gvwr,
        "hazmat_endorsed": hazmat,
        "service_status": "IN_SERVICE",
        "version": 1,
    }
    db.stamp(rec)
    store.vehicles[rec["id"]] = rec
    return ok(db.public(rec), 201)


@bp.get("/api/vehicles")
def list_vehicles():
    return list_response(
        store.vehicles.values(),
        [("carrier_id", "carrier_id"), ("service_status", "service_status")],
    )


@bp.get("/api/vehicles/<vehicleId>")
def get_vehicle(vehicleId):
    ctx()
    veh = store.vehicles.get(vehicleId)
    if veh is None:
        raise ApiError("ERR_VEHICLE_NOT_FOUND", 404, "vehicle id does not exist")
    return ok(db.public(veh), 200)


def _retire_cascade(vehicle):
    """Vehicle retirement cascades (PRD 3.4): credentials -> DEACTIVATED
    (VEHICLE_RETIRED); subscriptions -> CLOSED (VEHICLE_RETIRED)."""
    for cred in store.credentials.values():
        if cred["vehicle_id"] == vehicle["id"] and cred["status"] != "DEACTIVATED":
            cred["status"] = "DEACTIVATED"
            cred["status_reason"] = "VEHICLE_RETIRED"
            db.bump(cred)
    for sub in store.subscriptions.values():
        if sub["vehicle_id"] == vehicle["id"] and sub["status"] in (
            "SCHEDULED",
            "ACTIVE",
            "PAUSED",
        ):
            close_subscription(sub, "VEHICLE_RETIRED")


@bp.patch("/api/vehicles/<vehicleId>")
def patch_vehicle(vehicleId):
    uid, role = ctx()
    require_role(role, ("CarrierManager",))
    veh = store.vehicles.get(vehicleId)
    # Rung 3: ownership resolves through the vehicle when it exists
    if veh is not None:
        ownership_guard(veh["carrier_id"], uid)
    # Rung 4
    if veh is None:
        raise ApiError("ERR_VEHICLE_NOT_FOUND", 404, "vehicle id does not exist")
    body = body_json()
    target = body.get("service_status")
    # Rung 5 for valid enum members; rung 12 otherwise
    if isinstance(target, str) and target in SERVICE_STATUSES:
        if (veh["service_status"], target) not in _LEGAL_SERVICE:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                409,
                f"vehicle cannot move from {veh['service_status']} to {target}",
            )
    else:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "service_status must be one of IN_SERVICE, OUT_OF_SERVICE, RETIRED",
        )
    if target == "RETIRED":
        _retire_cascade(veh)
    veh["service_status"] = target
    db.bump(veh)
    return ok(db.public(veh), 200)
