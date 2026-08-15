"""Vehicles and transport dispatches."""
from datetime import timedelta

import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_SITE_NOT_OPEN,
    ERR_GUEST_ALREADY_HAS_ACTIVE_STAY, ERR_VEHICLE_WINDOW_CONFLICT,
    ERR_VEHICLE_TOO_SMALL, ERR_INSUFFICIENT_BEDS_FOR_DISPATCH,
    ERR_PET_CAPACITY_EXCEEDED, ERR_LOCKER_CAPACITY_EXCEEDED,
    ERR_INVALID_WINDOW, ERR_VALIDATION,
)
from flask import Blueprint, g, request
from response import respond, respond_list
from services import (
    guest_active_stay_in_episode, lockers_for_bags, pools, ser_dispatch,
    ser_vehicle,
)
from util import (
    body, opt_bool, opt_int, paginate, req_dt, req_int, req_list, req_str,
    touch,
)

bp = Blueprint("transport", __name__)


def get_vehicle(vehicle_id):
    v = db.store["vehicles"].get(vehicle_id)
    if v is None:
        raise_err(ERR_NOT_FOUND, f"Vehicle {vehicle_id} not found")
    return v


def get_dispatch(dispatch_id):
    d = db.store["dispatches"].get(dispatch_id)
    if d is None:
        raise_err(ERR_NOT_FOUND, f"TransportDispatch {dispatch_id} not found")
    return d


# ---------------------------------------------------------------- vehicles
@bp.route("/vehicles", methods=["POST"])
@require_roles("TransportCoordinator")
def create_vehicle():
    b = body()
    label = req_str(b, "label")
    seats = req_int(b, "seats", min_value=1)
    turnaround = opt_int(b, "turnaround_minutes", default=30, min_value=0)
    now = clock.now()
    v = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "label": label,
        "seats": seats,
        "turnaround_minutes": turnaround,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["vehicles"][v["id"]] = v
    return respond(ser_vehicle(v), 201)


@bp.route("/vehicles", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_vehicles():
    items = sorted(db.store["vehicles"].values(),
                   key=lambda v: (v["created_at"], v["_seq"]))
    page, pagination = paginate([ser_vehicle(v) for v in items])
    return respond_list(page, pagination)


# --------------------------------------------------------------- dispatches
@bp.route("/transport-dispatches", methods=["POST"])
@require_roles("OutreachWorker")
def create_dispatch():
    b = body()
    act = None
    if b.get("site_activation_id") is not None:
        act = db.store["activations"].get(b["site_activation_id"])
        if act is None:
            raise_err(
                ERR_NOT_FOUND,
                f"SiteActivation {b['site_activation_id']} not found",
            )
    guest_ids_raw = b.get("guest_ids")
    if isinstance(guest_ids_raw, list):
        for gid in guest_ids_raw:
            if not isinstance(gid, str) or gid not in db.store["guests"]:
                raise_err(ERR_NOT_FOUND, f"Guest {gid} not found")
    if act is None:
        if "site_activation_id" not in b or b["site_activation_id"] is None:
            raise_err(ERR_VALIDATION, "Missing required field: site_activation_id")
    if act["status"] != "OPEN":
        raise_err(
            ERR_SITE_NOT_OPEN,
            f"Dispatch destination must be OPEN (currently {act['status']})",
        )
    guest_ids = req_list(b, "guest_ids")
    if len(guest_ids) < 1:
        raise_err(ERR_VALIDATION, "guest_ids must contain at least one guest")
    pws = req_dt(b, "pickup_window_start")
    pwe = req_dt(b, "pickup_window_end")
    has_pets = opt_bool(b, "has_pets", default=False)
    if pwe <= pws:
        raise_err(
            ERR_INVALID_WINDOW,
            "pickup_window_end must be strictly after pickup_window_start",
        )
    now = clock.now()
    d = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "site_activation_id": act["id"],
        "vehicle_id": None,
        "requested_by_user_id": g.user_id,
        "guest_ids": list(guest_ids),
        "pickup_window_start": pws,
        "pickup_window_end": pwe,
        "has_pets": has_pets,
        "status": "REQUESTED",
        "arrived_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["dispatches"][d["id"]] = d
    return respond(ser_dispatch(d), 201)


@bp.route("/transport-dispatches", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_dispatches():
    items = list(db.store["dispatches"].values())
    act_id = request.args.get("site_activation_id")
    vehicle_id = request.args.get("vehicle_id")
    status = request.args.get("status")
    if act_id is not None:
        items = [d for d in items if d["site_activation_id"] == act_id]
    if vehicle_id is not None:
        items = [d for d in items if d["vehicle_id"] == vehicle_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda d: (d["created_at"], d["_seq"]))
    page, pagination = paginate([ser_dispatch(d) for d in items])
    return respond_list(page, pagination)


@bp.route("/transport-dispatches/<dispatch_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_dispatch(dispatch_id):
    return respond(ser_dispatch(get_dispatch(dispatch_id)), 200)


@bp.route("/transport-dispatches/<dispatch_id>/assign", methods=["POST"])
@require_roles("TransportCoordinator")
def assign_dispatch(dispatch_id):
    d = get_dispatch(dispatch_id)
    b = body()
    vehicle = None
    if b.get("vehicle_id") is not None:
        vehicle = get_vehicle(b["vehicle_id"])
    act = db.store["activations"].get(d["site_activation_id"])
    if act is None or act["status"] != "OPEN":
        raise_err(ERR_SITE_NOT_OPEN, "Destination activation is not OPEN")
    if d["status"] != "REQUESTED":
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot assign a dispatch in status {d['status']}",
        )
    if vehicle is None:
        if "vehicle_id" not in b or b["vehicle_id"] is None:
            raise_err(ERR_VALIDATION, "Missing required field: vehicle_id")
        vehicle = get_vehicle(b["vehicle_id"])
    episode_id = act["episode_id"]
    riders = len(d["guest_ids"])
    for gid in d["guest_ids"]:
        if guest_active_stay_in_episode(gid, episode_id):
            raise_err(
                ERR_GUEST_ALREADY_HAS_ACTIVE_STAY,
                f"Guest {gid} already has an active stay in this episode",
            )
    buffer = timedelta(minutes=vehicle["turnaround_minutes"])
    for other in db.store["dispatches"].values():
        if (other["id"] != d["id"]
                and other["vehicle_id"] == vehicle["id"]
                and other["status"] == "ASSIGNED"):
            exp_start = other["pickup_window_start"] - buffer
            exp_end = other["pickup_window_end"] + buffer
            if (d["pickup_window_start"] < exp_end
                    and exp_start < d["pickup_window_end"]):
                raise_err(
                    ERR_VEHICLE_WINDOW_CONFLICT,
                    "Vehicle has a conflicting dispatch window including "
                    "the turnaround buffer",
                )
    if vehicle["seats"] < riders:
        raise_err(ERR_VEHICLE_TOO_SMALL, "Vehicle seats < rider count")
    p = pools(act)
    if p["beds_free"] is None or p["beds_free"] < riders:
        raise_err(
            ERR_INSUFFICIENT_BEDS_FOR_DISPATCH,
            "Not enough free beds for the whole rider party",
        )
    guests = [db.store["guests"][gid] for gid in d["guest_ids"]]
    if d["has_pets"]:
        pets_needed = sum(gu["pet_count"] for gu in guests)
        if pets_needed > p["pet_slots_free"]:
            raise_err(ERR_PET_CAPACITY_EXCEEDED, "Not enough free pet slots")
    lockers_needed = sum(lockers_for_bags(gu["bag_count"]) for gu in guests)
    if lockers_needed > p["lockers_free"]:
        raise_err(ERR_LOCKER_CAPACITY_EXCEEDED, "Not enough free lockers")
    d["vehicle_id"] = vehicle["id"]
    d["status"] = "ASSIGNED"
    touch(d)
    now = clock.now()
    for gu in guests:
        stay = {
            "id": db.new_id(),
            "_seq": db.next_seq(),
            "site_activation_id": act["id"],
            "guest_id": gu["id"],
            "transport_dispatch_id": d["id"],
            "status": "RESERVED",
            "pet_slots_used": gu["pet_count"],
            "lockers_used": lockers_for_bags(gu["bag_count"]),
            "checked_in_at": None,
            "checked_out_at": None,
            "transfer_sequence": 0,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.store["stays"][stay["id"]] = stay
    return respond(ser_dispatch(d), 200)


@bp.route("/transport-dispatches/<dispatch_id>/arrive", methods=["POST"])
@require_roles("TransportCoordinator")
def arrive_dispatch(dispatch_id):
    d = get_dispatch(dispatch_id)
    if d["status"] != "ASSIGNED":
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot arrive a dispatch in status {d['status']}",
        )
    d["status"] = "ARRIVED"
    d["arrived_at"] = clock.now()
    touch(d)
    return respond(ser_dispatch(d), 200)


@bp.route("/transport-dispatches/<dispatch_id>/cancel", methods=["POST"])
@require_roles("OutreachWorker", "TransportCoordinator")
def cancel_dispatch(dispatch_id):
    d = get_dispatch(dispatch_id)
    if d["status"] not in ("REQUESTED", "ASSIGNED"):
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot cancel a dispatch in status {d['status']}",
        )
    if d["status"] == "ASSIGNED":
        for s in db.store["stays"].values():
            if (s["transport_dispatch_id"] == d["id"]
                    and s["status"] == "RESERVED"):
                s["status"] = "CANCELLED"
                touch(s)
    d["status"] = "CANCELLED"
    touch(d)
    return respond(ser_dispatch(d), 200)
