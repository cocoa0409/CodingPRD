"""FleetVehicle and FleetDispatch endpoints: booking (closed-window, adjacency
counts as overlap), checkout, return with late fine, maintenance cascade."""
from flask import Blueprint, request

import db
from db import touch
from errors import (err_not_found, err_invalid_state, err_holder_not_eligible,
                    err_dispatch_overlap, err_fleet_unavailable,
                    err_insufficient_funds)
from middleware import get_caller, require_role, check_holder_ownership
from response import ok_object, ok_list
from services import calc, validate as v
from services.serializers import base_entity, fleet_vehicle_view, fleet_dispatch_view

bp = Blueprint("fleet", __name__)

READ_ROLES = ["PlatformAdmin", "CommunityAdmin", "Inspector", "EnforcementOfficer", "PermitHolder"]


# ---------------------------------------------------------------------------
# Fleet vehicles
# ---------------------------------------------------------------------------
@bp.post("/api/fleet-vehicles")
def create_fleet_vehicle():
    data = v.body()
    community_id = v.require_str(data, "community_id")
    station_id = v.require_str(data, "station_id")
    label = v.require_str(data, "label")
    caller = get_caller()
    require_role(caller, ["CommunityAdmin"])
    if db.communities.get(community_id) is None:
        raise err_not_found("Community not found")
    if db.charging_stations.get(station_id) is None:
        raise err_not_found("ChargingStation not found")

    fv = base_entity()
    fv.update({
        "community_id": community_id,
        "station_id": station_id,
        "label": label,
        "status": "AVAILABLE",
    })
    db.fleet_vehicles[fv["id"]] = fv
    return ok_object(fleet_vehicle_view(fv), 201)


@bp.get("/api/fleet-vehicles/<vid>")
def get_fleet_vehicle(vid):
    caller = get_caller()
    require_role(caller, READ_ROLES)
    fv = db.fleet_vehicles.get(vid)
    if fv is None:
        raise err_not_found("FleetVehicle not found")
    return ok_object(fleet_vehicle_view(fv))


@bp.get("/api/fleet-vehicles")
def list_fleet_vehicles():
    caller = get_caller()
    require_role(caller, READ_ROLES)
    limit, offset = v.pagination_args()
    community_id = request.args.get("community_id")
    station_id = request.args.get("station_id")
    rows = list(db.fleet_vehicles.values())
    if community_id is not None:
        rows = [x for x in rows if x["community_id"] == community_id]
    if station_id is not None:
        rows = [x for x in rows if x["station_id"] == station_id]
    rows = v.sorted_by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([fleet_vehicle_view(x) for x in page], limit, offset, total)


@bp.post("/api/fleet-vehicles/<vid>/set-maintenance")
def set_maintenance(vid):
    caller = get_caller()
    require_role(caller, ["CommunityAdmin"])
    fv = db.fleet_vehicles.get(vid)
    if fv is None:
        raise err_not_found("FleetVehicle not found")
    if fv["status"] != "AVAILABLE":
        raise err_invalid_state("Fleet vehicle is not AVAILABLE")
    fv["status"] = "MAINTENANCE"
    touch(fv)
    now_dt = db.now()
    for d in db.fleet_dispatches.values():
        if d["vehicle_id"] == vid and d["status"] == "BOOKED" and d["shift_start"] > now_dt:
            d["status"] = "CANCELLED"
            touch(d)
    return ok_object(fleet_vehicle_view(fv))


@bp.post("/api/fleet-vehicles/<vid>/set-available")
def set_available(vid):
    caller = get_caller()
    require_role(caller, ["CommunityAdmin"])
    fv = db.fleet_vehicles.get(vid)
    if fv is None:
        raise err_not_found("FleetVehicle not found")
    if fv["status"] != "MAINTENANCE":
        raise err_invalid_state("Fleet vehicle is not MAINTENANCE")
    fv["status"] = "AVAILABLE"
    touch(fv)
    return ok_object(fleet_vehicle_view(fv))


# ---------------------------------------------------------------------------
# Fleet dispatches
# ---------------------------------------------------------------------------
@bp.post("/api/fleet-dispatches")
def create_dispatch():
    data = v.body()
    vehicle_id = v.require_str(data, "vehicle_id")
    holder_id = v.require_str(data, "holder_id")
    shift_start, shift_end = v.require_window(data, "shift_start", "shift_end")
    caller = get_caller()
    require_role(caller, ["PermitHolder"])
    check_holder_ownership(caller, holder_id)
    # Stage 4: body FKs in declared order
    fv = db.fleet_vehicles.get(vehicle_id)
    if fv is None:
        raise err_not_found("FleetVehicle not found")
    holder = db.permit_holders.get(holder_id)
    if holder is None:
        raise err_not_found("PermitHolder not found")
    # Stage 7: closed-window overlap per vehicle — adjacency counts as overlap
    for d in db.fleet_dispatches.values():
        if d["vehicle_id"] != vehicle_id:
            continue
        if d["status"] in ("RETURNED", "CANCELLED"):
            continue
        if shift_start <= d["shift_end"] and d["shift_start"] <= shift_end:
            raise err_dispatch_overlap()
    # Stage 8: holder ELIGIBLE
    if holder["eligibility_status"] != "ELIGIBLE":
        raise err_holder_not_eligible()

    d = base_entity()
    d.update({
        "vehicle_id": vehicle_id,
        "holder_id": holder_id,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "status": "BOOKED",
        "returned_at": None,
        "late_fine_cents": 0,
    })
    db.fleet_dispatches[d["id"]] = d
    return ok_object(fleet_dispatch_view(d), 201)


@bp.get("/api/fleet-dispatches/<did>")
def get_dispatch(did):
    caller = get_caller()
    require_role(caller, READ_ROLES)
    d = db.fleet_dispatches.get(did)
    if d is None:
        raise err_not_found("FleetDispatch not found")
    check_holder_ownership(caller, d["holder_id"])
    return ok_object(fleet_dispatch_view(d))


@bp.get("/api/fleet-dispatches")
def list_dispatches():
    caller = get_caller()
    require_role(caller, READ_ROLES)
    limit, offset = v.pagination_args()
    vehicle_id = request.args.get("vehicle_id")
    holder_id = request.args.get("holder_id")
    rows = list(db.fleet_dispatches.values())
    if vehicle_id is not None:
        rows = [d for d in rows if d["vehicle_id"] == vehicle_id]
    if holder_id is not None:
        rows = [d for d in rows if d["holder_id"] == holder_id]
    if caller.role == "PermitHolder":
        rows = [d for d in rows if d["holder_id"] == caller.user_id]
    rows = v.sorted_by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([fleet_dispatch_view(d) for d in page], limit, offset, total)


@bp.post("/api/fleet-dispatches/<did>/checkout")
def checkout_dispatch(did):
    caller = get_caller()
    require_role(caller, ["PermitHolder"])
    d = db.fleet_dispatches.get(did)
    if d is None:
        raise err_not_found("FleetDispatch not found")
    check_holder_ownership(caller, d["holder_id"])
    if d["status"] != "BOOKED":
        raise err_invalid_state("Dispatch is not BOOKED")
    if not (db.now() >= d["shift_start"]):
        raise err_invalid_state("Shift window has not begun")
    fv = db.fleet_vehicles.get(d["vehicle_id"])
    if fv["status"] != "AVAILABLE":
        raise err_fleet_unavailable()
    fv["status"] = "CHECKED_OUT"
    touch(fv)
    d["status"] = "CHECKED_OUT"
    touch(d)
    community = db.communities.get(fv["community_id"])
    if community is not None:
        community["checked_out_count"] += 1
        touch(community)
    return ok_object(fleet_dispatch_view(d))


@bp.post("/api/fleet-dispatches/<did>/return")
def return_dispatch(did):
    caller = get_caller()
    require_role(caller, ["PermitHolder"])
    d = db.fleet_dispatches.get(did)
    if d is None:
        raise err_not_found("FleetDispatch not found")
    check_holder_ownership(caller, d["holder_id"])
    if d["status"] not in ("CHECKED_OUT", "OVERDUE"):
        raise err_invalid_state("Dispatch is not CHECKED_OUT or OVERDUE")
    now_dt = db.now()
    fine = calc.fleet_late_fine(d["shift_end"], now_dt)
    holder = db.permit_holders.get(d["holder_id"])
    if fine > 0 and holder["wallet_balance_cents"] < fine:
        raise err_insufficient_funds()
    d["returned_at"] = now_dt
    d["late_fine_cents"] = fine
    d["status"] = "RETURNED"
    touch(d)
    fv = db.fleet_vehicles.get(d["vehicle_id"])
    fv["status"] = "AVAILABLE"
    touch(fv)
    community = db.communities.get(fv["community_id"])
    if community is not None:
        community["checked_out_count"] -= 1
        touch(community)
    if fine > 0:
        holder["wallet_balance_cents"] -= fine
        touch(holder)
    return ok_object(fleet_dispatch_view(d))


@bp.post("/api/fleet-dispatches/<did>/cancel")
def cancel_dispatch(did):
    caller = get_caller()
    require_role(caller, ["PermitHolder"])
    d = db.fleet_dispatches.get(did)
    if d is None:
        raise err_not_found("FleetDispatch not found")
    check_holder_ownership(caller, d["holder_id"])
    if d["status"] != "BOOKED":
        raise err_invalid_state("Dispatch is not BOOKED")
    if not (db.now() < d["shift_start"]):
        raise err_invalid_state("Shift window has begun; cannot cancel")
    d["status"] = "CANCELLED"
    touch(d)
    return ok_object(fleet_dispatch_view(d))
