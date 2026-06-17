"""Site, Floor, Neighborhood, Seat, Room, CapacityPolicy routes + utilization.

All read endpoints are shared across roles per RBAC; mutations are
FacilityManager-only (PRD §3.1/§3.2/§3.3, scaffold §1.5/§1.7).
"""
from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    APIError,
    ERR_DUPLICATE,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_RESOURCE_NOT_BOOKABLE,
)
from middleware import require_role
from response import ok_object, ok_array
from routes._helpers import (
    parse_pagination, paginate, order_by_created, get_body,
    require_str, optional_int, optional_bool, require_int,
    get_site, get_floor, get_neighborhood, get_seat, get_room,
)
from services.common import stamp_new, touch, public, public_list
from services import calculations as calc

READ_ROLES = ("FacilityManager", "Analyst", "Receptionist", "Employee")

bp = Blueprint("sites", __name__)


# ---- Sites ----------------------------------------------------------------

@bp.post("/workplace/sites")
def create_site():
    require_role("FacilityManager")
    body = get_body()
    name = require_str(body, "name", max_len=120)
    timezone = body.get("timezone", "UTC")
    if timezone is None:
        timezone = "UTC"
    if not isinstance(timezone, str) or isinstance(timezone, bool):
        raise APIError(ERR_INVALID_REQUEST, 422, "timezone must be a string")
    site = {
        "name": name,
        "timezone": timezone,
        "status": "ACTIVE",
    }
    stamp_new(site)
    db.sites[site["id"]] = site
    return ok_object(public(site), 201)


@bp.get("/workplace/sites/<sid>")
def get_site_ep(sid):
    require_role(*READ_ROLES)
    site = get_site(sid)
    return ok_object(public(site))


# ---- Floors ---------------------------------------------------------------

@bp.post("/workplace/sites/<sid>/floors")
def create_floor(sid):
    require_role("FacilityManager")
    site = get_site(sid)
    body = get_body()
    level = require_int(body, "level")
    start = optional_int(body, "workday_start_minute", 540)
    end = optional_int(body, "workday_end_minute", 1080)
    # window constraint: 0 <= start < end <= 1440
    if not (0 <= start < end <= 1440):
        raise APIError(ERR_INVALID_REQUEST, 422,
                       "workday window must satisfy 0 <= start < end <= 1440")
    # unique level per site
    for f in db.floors.values():
        if f["site_id"] == site["id"] and f["level"] == level:
            raise APIError(ERR_DUPLICATE, 409, "Floor level already exists for this site")
    floor = {
        "site_id": site["id"],
        "level": level,
        "workday_start_minute": start,
        "workday_end_minute": end,
        "capacity_minutes": end - start,
        "status": "ACTIVE",
    }
    stamp_new(floor)
    db.floors[floor["id"]] = floor
    return ok_object(public(floor), 201)


@bp.get("/workplace/sites/<sid>/floors")
def list_floors(sid):
    require_role(*READ_ROLES)
    site = get_site(sid)
    limit, offset = parse_pagination()
    items = [f for f in db.floors.values() if f["site_id"] == site["id"]]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(public_list(page), limit, offset, total)


@bp.get("/workplace/floors/<fid>")
def get_floor_ep(fid):
    require_role(*READ_ROLES)
    floor = get_floor(fid)
    return ok_object(public(floor))


@bp.get("/workplace/floors/<fid>/utilization")
def floor_utilization(fid):
    require_role("FacilityManager", "Analyst")
    floor = get_floor(fid)
    from flask import request
    date = request.args.get("date")
    if not date or not isinstance(date, str):
        raise APIError(ERR_INVALID_REQUEST, 422, "date query param required")
    mode = request.args.get("mode", "PLANNED")
    if mode not in ("PLANNED", "REALIZED"):
        raise APIError(ERR_INVALID_REQUEST, 422, "mode must be PLANNED or REALIZED")
    report = calc.utilization_report(floor, date, mode)
    return ok_object(report)


# ---- Capacity policy (per floor) ------------------------------------------

@bp.post("/workplace/floors/<fid>/capacity-policy")
def create_capacity_policy(fid):
    require_role("FacilityManager")
    floor = get_floor(fid)
    body = get_body()
    max_active = optional_int(body, "max_active_reservations_per_employee", 1, minimum=1)
    grace = optional_int(body, "grace_minutes", 30, minimum=0)
    enforce = optional_bool(body, "enforce_team_zoning", True)
    # create/replace: drop existing policy for this floor
    existing_id = None
    for pid, p in db.capacity_policies.items():
        if p["floor_id"] == floor["id"]:
            existing_id = pid
            break
    if existing_id is not None:
        del db.capacity_policies[existing_id]
    policy = {
        "floor_id": floor["id"],
        "max_active_reservations_per_employee": max_active,
        "grace_minutes": grace,
        "enforce_team_zoning": enforce,
    }
    stamp_new(policy)
    db.capacity_policies[policy["id"]] = policy
    return ok_object(public(policy), 201)


@bp.get("/workplace/floors/<fid>/capacity-policy")
def list_capacity_policy(fid):
    require_role("FacilityManager", "Analyst")
    floor = get_floor(fid)
    limit, offset = parse_pagination()
    items = [p for p in db.capacity_policies.values() if p["floor_id"] == floor["id"]]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(public_list(page), limit, offset, total)


# ---- Neighborhoods --------------------------------------------------------

@bp.post("/workplace/floors/<fid>/neighborhoods")
def create_neighborhood(fid):
    require_role("FacilityManager")
    floor = get_floor(fid)
    body = get_body()
    name = require_str(body, "name")
    team_code = body.get("team_code", None)
    if team_code is not None and (not isinstance(team_code, str) or isinstance(team_code, bool)):
        raise APIError(ERR_INVALID_REQUEST, 422, "team_code must be a string or null")
    cap_pct = optional_int(body, "capacity_cap_pct", 100, minimum=1, maximum=100)
    # unique name per floor
    for n in db.neighborhoods.values():
        if n["floor_id"] == floor["id"] and n["name"] == name:
            raise APIError(ERR_DUPLICATE, 409, "Neighborhood name already exists on this floor")
    neigh = {
        "floor_id": floor["id"],
        "name": name,
        "team_code": team_code,
        "capacity_cap_pct": cap_pct,
        "seat_count": 0,
        "effective_cap_seats": 0,
    }
    stamp_new(neigh)
    db.neighborhoods[neigh["id"]] = neigh
    return ok_object(public(neigh), 201)


@bp.get("/workplace/floors/<fid>/neighborhoods")
def list_neighborhoods(fid):
    require_role(*READ_ROLES)
    floor = get_floor(fid)
    limit, offset = parse_pagination()
    items = [n for n in db.neighborhoods.values() if n["floor_id"] == floor["id"]]
    for n in items:
        calc.recompute_neighborhood(n)
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(public_list(page), limit, offset, total)


@bp.get("/workplace/neighborhoods/<nid>")
def get_neighborhood_ep(nid):
    require_role(*READ_ROLES)
    neigh = get_neighborhood(nid)
    calc.recompute_neighborhood(neigh)
    return ok_object(public(neigh))


# ---- Seats ----------------------------------------------------------------

@bp.post("/workplace/neighborhoods/<nid>/seats")
def create_seat(nid):
    require_role("FacilityManager")
    neigh = get_neighborhood(nid)
    body = get_body()
    label = require_str(body, "label")
    is_standing = optional_bool(body, "is_standing", False)
    for s in db.seats.values():
        if s["neighborhood_id"] == neigh["id"] and s["label"] == label:
            raise APIError(ERR_DUPLICATE, 409, "Seat label already exists in this neighborhood")
    seat = {
        "neighborhood_id": neigh["id"],
        "label": label,
        "is_standing": is_standing,
        "status": "AVAILABLE",
    }
    stamp_new(seat)
    db.seats[seat["id"]] = seat
    # increment seat_count; recompute effective_cap_seats (mutates neighborhood)
    calc.recompute_neighborhood(neigh)
    touch(neigh)
    return ok_object(public(seat), 201)


@bp.get("/workplace/neighborhoods/<nid>/seats")
def list_seats(nid):
    require_role(*READ_ROLES)
    neigh = get_neighborhood(nid)
    limit, offset = parse_pagination()
    items = [s for s in db.seats.values() if s["neighborhood_id"] == neigh["id"]]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(public_list(page), limit, offset, total)


@bp.get("/workplace/seats/<sid>")
def get_seat_ep(sid):
    require_role(*READ_ROLES)
    seat = get_seat(sid)
    return ok_object(public(seat))


@bp.post("/workplace/seats/<sid>/out-of-service")
def seat_out_of_service(sid):
    require_role("FacilityManager")
    seat = get_seat(sid)
    if seat["status"] != "AVAILABLE":
        raise APIError(ERR_INVALID_STATE, 409, "Seat not AVAILABLE")
    seat["status"] = "OUT_OF_SERVICE"
    touch(seat)
    return ok_object(public(seat))


@bp.post("/workplace/seats/<sid>/restore")
def seat_restore(sid):
    require_role("FacilityManager")
    seat = get_seat(sid)
    if seat["status"] != "OUT_OF_SERVICE":
        raise APIError(ERR_INVALID_STATE, 409, "Seat not OUT_OF_SERVICE")
    seat["status"] = "AVAILABLE"
    touch(seat)
    return ok_object(public(seat))


@bp.post("/workplace/seats/<sid>/retire")
def seat_retire(sid):
    require_role("FacilityManager")
    seat = get_seat(sid)
    if seat["status"] != "AVAILABLE":
        raise APIError(ERR_INVALID_STATE, 409, "Seat not AVAILABLE")
    # no reservation on this seat in BOOKED/CHECKED_IN
    for r in db.reservations.values():
        if r["resource_type"] == "SEAT" and r["seat_id"] == seat["id"] \
                and r["occupancy_status"] in ("BOOKED", "CHECKED_IN"):
            raise APIError(ERR_INVALID_STATE, 409, "Seat has live bookings")
    seat["status"] = "RETIRED"
    touch(seat)
    neigh = db.neighborhoods.get(seat["neighborhood_id"])
    if neigh is not None:
        calc.recompute_neighborhood(neigh)
        touch(neigh)
    return ok_object(public(seat))


# ---- Rooms ----------------------------------------------------------------

@bp.post("/workplace/floors/<fid>/rooms")
def create_room(fid):
    require_role("FacilityManager")
    floor = get_floor(fid)
    body = get_body()
    label = require_str(body, "label")
    seats_capacity = require_int(body, "seats_capacity", minimum=1)
    turnover = optional_int(body, "turnover_buffer_minute", 15, minimum=0)
    for rm in db.rooms.values():
        if rm["floor_id"] == floor["id"] and rm["label"] == label:
            raise APIError(ERR_DUPLICATE, 409, "Room label already exists on this floor")
    room = {
        "floor_id": floor["id"],
        "label": label,
        "seats_capacity": seats_capacity,
        "turnover_buffer_minute": turnover,
        "status": "AVAILABLE",
    }
    stamp_new(room)
    db.rooms[room["id"]] = room
    return ok_object(public(room), 201)


@bp.get("/workplace/floors/<fid>/rooms")
def list_rooms(fid):
    require_role(*READ_ROLES)
    floor = get_floor(fid)
    limit, offset = parse_pagination()
    items = [rm for rm in db.rooms.values() if rm["floor_id"] == floor["id"]]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(public_list(page), limit, offset, total)


@bp.get("/workplace/rooms/<rid>")
def get_room_ep(rid):
    require_role(*READ_ROLES)
    room = get_room(rid)
    return ok_object(public(room))
