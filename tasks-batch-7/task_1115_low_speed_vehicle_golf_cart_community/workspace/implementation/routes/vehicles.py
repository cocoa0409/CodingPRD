"""Vehicle endpoints: create with equipment declaration, read, list, retire."""
from flask import Blueprint, request

import db
from db import touch
from errors import err_not_found, err_invalid_state
from middleware import get_caller, require_role, check_holder_ownership
from response import ok_object, ok_list
from services import calc, validate as v
from services.serializers import base_entity, vehicle_view

bp = Blueprint("vehicles", __name__)

READ_ROLES = ["PlatformAdmin", "CommunityAdmin", "Inspector", "EnforcementOfficer", "PermitHolder"]

EQUIP_BOOL_FIELDS = ["has_headlights", "has_brake_lights", "has_turn_signals", "has_horn",
                     "has_windshield", "has_seatbelts", "has_reflectors"]


@bp.post("/api/vehicles")
def create_vehicle():
    data = v.body()
    # Stage 1: schema
    holder_id = v.require_str(data, "holder_id")
    vehicle_type = v.require_enum(data, "vehicle_type", {"GOLF_CART", "LSV"})
    seat_count = v.require_int(data, "seat_count", 1, 8)
    flags = {f: v.require_bool(data, f) for f in EQUIP_BOOL_FIELDS}
    mirror_count = v.require_int(data, "mirror_count", 0, 4)
    # Stage 2-3
    caller = get_caller()
    require_role(caller, ["PermitHolder"])
    check_holder_ownership(caller, holder_id)
    # Stage 4
    holder = db.permit_holders.get(holder_id)
    if holder is None:
        raise err_not_found("PermitHolder not found")

    veh = base_entity()
    veh.update({
        "holder_id": holder_id,
        "vehicle_type": vehicle_type,
        "seat_count": seat_count,
        "mirror_count": mirror_count,
        "vehicle_status": "ACTIVE",
    })
    veh.update(flags)
    veh["equipment_count"] = calc.equipment_count(veh)
    db.vehicles[veh["id"]] = veh
    return ok_object(vehicle_view(veh), 201)


@bp.get("/api/vehicles/<vid>")
def get_vehicle(vid):
    caller = get_caller()
    require_role(caller, READ_ROLES)
    veh = db.vehicles.get(vid)
    if veh is None:
        raise err_not_found("Vehicle not found")
    check_holder_ownership(caller, veh["holder_id"])
    return ok_object(vehicle_view(veh))


@bp.get("/api/vehicles")
def list_vehicles():
    caller = get_caller()
    require_role(caller, READ_ROLES)
    limit, offset = v.pagination_args()
    holder_filter = request.args.get("holder_id")
    rows = list(db.vehicles.values())
    if holder_filter is not None:
        rows = [x for x in rows if x["holder_id"] == holder_filter]
    if caller.role == "PermitHolder":
        rows = [x for x in rows if x["holder_id"] == caller.user_id]
    rows = v.sorted_by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([vehicle_view(x) for x in page], limit, offset, total)


@bp.post("/api/vehicles/<vid>/retire")
def retire_vehicle(vid):
    caller = get_caller()
    require_role(caller, ["PermitHolder"])
    veh = db.vehicles.get(vid)
    if veh is None:
        raise err_not_found("Vehicle not found")
    check_holder_ownership(caller, veh["holder_id"])
    # Stage 5: state machine from-state
    if veh["vehicle_status"] != "ACTIVE":
        raise err_invalid_state("Vehicle is not ACTIVE")
    # Precondition: no registration in DRAFT/ACTIVE/RENEWAL_PENDING/SUSPENDED
    for reg in db.registrations.values():
        if reg["vehicle_id"] == vid and reg["status"] in ("DRAFT", "ACTIVE", "RENEWAL_PENDING", "SUSPENDED"):
            raise err_invalid_state("Vehicle has a non-terminal registration")
    veh["vehicle_status"] = "RETIRED"
    touch(veh)
    return ok_object(vehicle_view(veh))
