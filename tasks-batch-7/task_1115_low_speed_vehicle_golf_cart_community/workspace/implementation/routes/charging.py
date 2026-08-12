"""ChargingStation and ChargingReservation endpoints, incl. station offline
cascade with wallet refunds and the closed-interval + 15-minute buffer rule."""
from datetime import timedelta
from flask import Blueprint, request

import db
from db import touch
from errors import (err_not_found, err_invalid_state, err_station_offline,
                    err_charging_overlap, err_insufficient_funds)
from middleware import get_caller, require_role, check_holder_ownership
from response import ok_object, ok_list
from services import calc, validate as v
from services.serializers import base_entity, charging_station_view, charging_reservation_view

bp = Blueprint("charging", __name__)

READ_ROLES = ["PlatformAdmin", "CommunityAdmin", "Inspector", "EnforcementOfficer", "PermitHolder"]
BUFFER = timedelta(minutes=15)


# ---------------------------------------------------------------------------
# Stations
# ---------------------------------------------------------------------------
@bp.post("/api/charging-stations")
def create_station():
    data = v.body()
    community_id = v.require_str(data, "community_id")
    name = v.require_str(data, "name")
    slot_count = v.require_int(data, "slot_count", 1, 20)
    rate = v.require_int(data, "rate_cents_per_min", 1, None)
    caller = get_caller()
    require_role(caller, ["CommunityAdmin"])
    if db.communities.get(community_id) is None:
        raise err_not_found("Community not found")

    s = base_entity()
    s.update({
        "community_id": community_id,
        "name": name,
        "slot_count": slot_count,
        "rate_cents_per_min": rate,
        "status": "ONLINE",
    })
    db.charging_stations[s["id"]] = s
    return ok_object(charging_station_view(s), 201)


@bp.get("/api/charging-stations/<sid>")
def get_station(sid):
    caller = get_caller()
    require_role(caller, READ_ROLES)
    s = db.charging_stations.get(sid)
    if s is None:
        raise err_not_found("ChargingStation not found")
    return ok_object(charging_station_view(s))


@bp.get("/api/charging-stations")
def list_stations():
    caller = get_caller()
    require_role(caller, READ_ROLES)
    limit, offset = v.pagination_args()
    community_id = request.args.get("community_id")
    rows = list(db.charging_stations.values())
    if community_id is not None:
        rows = [s for s in rows if s["community_id"] == community_id]
    rows = v.sorted_by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([charging_station_view(s) for s in page], limit, offset, total)


@bp.post("/api/charging-stations/<sid>/set-offline")
def set_offline(sid):
    caller = get_caller()
    require_role(caller, ["CommunityAdmin"])
    s = db.charging_stations.get(sid)
    if s is None:
        raise err_not_found("ChargingStation not found")
    if s["status"] != "ONLINE":
        raise err_invalid_state("Station is not ONLINE")
    s["status"] = "OFFLINE"
    touch(s)
    now_dt = db.now()
    # Cascade: future BOOKED reservations -> CANCELLED with full wallet refund
    for r in db.charging_reservations.values():
        if r["station_id"] == sid and r["status"] == "BOOKED" and r["start_at"] > now_dt:
            r["status"] = "CANCELLED"
            touch(r)
            holder = db.permit_holders.get(r["holder_id"])
            if holder is not None:
                holder["wallet_balance_cents"] += r["fee_cents"]
                touch(holder)
    return ok_object(charging_station_view(s))


@bp.post("/api/charging-stations/<sid>/set-online")
def set_online(sid):
    caller = get_caller()
    require_role(caller, ["CommunityAdmin"])
    s = db.charging_stations.get(sid)
    if s is None:
        raise err_not_found("ChargingStation not found")
    if s["status"] != "OFFLINE":
        raise err_invalid_state("Station is not OFFLINE")
    s["status"] = "ONLINE"
    touch(s)
    return ok_object(charging_station_view(s))


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------
@bp.post("/api/charging-reservations")
def create_reservation():
    data = v.body()
    station_id = v.require_str(data, "station_id")
    holder_id = v.require_str(data, "holder_id")
    slot_index = v.require_int(data, "slot_index", 0, None)
    start_at, end_at = v.require_window(data, "start_at", "end_at")
    caller = get_caller()
    require_role(caller, ["PermitHolder"])
    check_holder_ownership(caller, holder_id)
    # Stage 4: body FKs in declared order
    station = db.charging_stations.get(station_id)
    if station is None:
        raise err_not_found("ChargingStation not found")
    holder = db.permit_holders.get(holder_id)
    if holder is None:
        raise err_not_found("PermitHolder not found")
    # slot_index within the station's bays
    if slot_index >= station["slot_count"]:
        from errors import err_validation
        raise err_validation("slot_index out of range for the station")
    # Stage 7: closed-interval + 15-minute buffer overlap per (station, slot)
    new_lo, new_hi = start_at - BUFFER, end_at + BUFFER
    for r in db.charging_reservations.values():
        if r["station_id"] != station_id or r["slot_index"] != slot_index:
            continue
        if r["status"] != "BOOKED":
            continue
        ex_lo, ex_hi = r["start_at"] - BUFFER, r["end_at"] + BUFFER
        # closed buffered intervals: any touch counts as collision
        if new_lo <= ex_hi and ex_lo <= new_hi:
            raise err_charging_overlap()
    # Stage 8: station ONLINE
    if station["status"] != "ONLINE":
        raise err_station_offline()
    # Stage 10: wallet sufficiency
    fee = calc.charging_fee(start_at, end_at, station["rate_cents_per_min"])
    if holder["wallet_balance_cents"] < fee:
        raise err_insufficient_funds()

    holder["wallet_balance_cents"] -= fee
    touch(holder)
    r = base_entity()
    r.update({
        "station_id": station_id,
        "holder_id": holder_id,
        "slot_index": slot_index,
        "start_at": start_at,
        "end_at": end_at,
        "fee_cents": fee,
        "status": "BOOKED",
    })
    db.charging_reservations[r["id"]] = r
    return ok_object(charging_reservation_view(r), 201)


@bp.get("/api/charging-reservations/<rid>")
def get_reservation(rid):
    caller = get_caller()
    require_role(caller, READ_ROLES)
    r = db.charging_reservations.get(rid)
    if r is None:
        raise err_not_found("ChargingReservation not found")
    check_holder_ownership(caller, r["holder_id"])
    return ok_object(charging_reservation_view(r))


@bp.get("/api/charging-reservations")
def list_reservations():
    caller = get_caller()
    require_role(caller, READ_ROLES)
    limit, offset = v.pagination_args()
    station_id = request.args.get("station_id")
    holder_id = request.args.get("holder_id")
    rows = list(db.charging_reservations.values())
    if station_id is not None:
        rows = [r for r in rows if r["station_id"] == station_id]
    if holder_id is not None:
        rows = [r for r in rows if r["holder_id"] == holder_id]
    if caller.role == "PermitHolder":
        rows = [r for r in rows if r["holder_id"] == caller.user_id]
    rows = v.sorted_by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([charging_reservation_view(r) for r in page], limit, offset, total)


@bp.post("/api/charging-reservations/<rid>/cancel")
def cancel_reservation(rid):
    caller = get_caller()
    require_role(caller, ["PermitHolder"])
    r = db.charging_reservations.get(rid)
    if r is None:
        raise err_not_found("ChargingReservation not found")
    check_holder_ownership(caller, r["holder_id"])
    if r["status"] != "BOOKED":
        raise err_invalid_state("Reservation is not BOOKED")
    if not (db.now() < r["start_at"]):
        raise err_invalid_state("Once the window begins the reservation cannot be cancelled")
    r["status"] = "CANCELLED"
    touch(r)
    holder = db.permit_holders.get(r["holder_id"])
    if holder is not None:
        holder["wallet_balance_cents"] += r["fee_cents"]
        touch(holder)
    return ok_object(charging_reservation_view(r))
