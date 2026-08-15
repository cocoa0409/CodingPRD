"""AidStation + VolunteerAssignment endpoints."""
from flask import Blueprint, request

import db
from errors import (ApiError, ERR_VALIDATION, ERR_INVALID_STATE, ERR_WATER_NOT_ALLOCATED,
                    ERR_SHIFT_OVERLAP, not_found)
from middleware import require_roles
from response import success_object, success_list, paginate
from services.core import recompute_readiness, refresh_water_pool
from util import stamp_common, touch, require_fields, require_int, require_number, parse_dt

bp = Blueprint("aid", __name__)

ALL = ("RaceDirector", "PermitCoordinator", "Referee", "Timer", "VolunteerCoordinator", "Athlete")


def get_event_or_404(event_id):
    ev = db.events.get(event_id)
    if not ev:
        raise not_found("event not found")
    return ev


def get_station_or_404(sid):
    s = db.aid_stations.get(sid)
    if not s:
        raise not_found("aid station not found")
    return s


def get_assignment_or_404(aid):
    a = db.volunteer_assignments.get(aid)
    if not a:
        raise not_found("volunteer assignment not found")
    return a


@bp.post("/events/<event_id>/aid-stations")
def create_station(event_id):
    require_roles("RaceDirector")
    get_event_or_404(event_id)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["name", "location_km", "required_volunteers", "required_water_units"])
    if not isinstance(body["name"], str) or not body["name"]:
        raise ApiError(ERR_VALIDATION, "name must be a non-empty string", 400)
    require_number(body["location_km"], "location_km")
    rv = require_int(body["required_volunteers"], "required_volunteers")
    rw = require_int(body["required_water_units"], "required_water_units")
    s = stamp_common({
        "event_id": event_id,
        "name": body["name"],
        "location_km": body["location_km"],
        "required_volunteers": rv,
        "required_water_units": rw,
        "allocated_water_units": 0,
        "confirmed_volunteer_count": 0,
        "readiness_status": "UNDERSTAFFED",
    })
    db.aid_stations[s["id"]] = s
    recompute_readiness(s)
    return success_object(s, status=201)


@bp.get("/events/<event_id>/aid-stations")
def list_stations(event_id):
    require_roles(*ALL)
    get_event_or_404(event_id)
    items = [s for s in db.aid_stations.values() if s["event_id"] == event_id]
    page, limit, offset, total = paginate(items, request.args)
    return success_list(page, limit, offset, total)


@bp.get("/aid-stations/<sid>")
def get_station(sid):
    require_roles(*ALL)
    s = get_station_or_404(sid)
    recompute_readiness(s)
    return success_object(s)


@bp.post("/aid-stations/<sid>/deallocate-water")
def deallocate_water(sid):
    require_roles("RaceDirector")
    s = get_station_or_404(sid)
    if s["allocated_water_units"] <= 0:
        raise ApiError(ERR_WATER_NOT_ALLOCATED, "station has no allocated water", 409)
    s["allocated_water_units"] = 0
    recompute_readiness(s)
    touch(s)
    ev = db.events[s["event_id"]]
    refresh_water_pool(ev)
    touch(ev)
    return success_object(s)


@bp.post("/aid-stations/<sid>/assignments")
def create_assignment(sid):
    require_roles("VolunteerCoordinator")
    s = get_station_or_404(sid)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["volunteer_id", "shift_start", "shift_end"])
    if not isinstance(body["volunteer_id"], str) or not body["volunteer_id"]:
        raise ApiError(ERR_VALIDATION, "volunteer_id must be a non-empty string", 400)
    ss = parse_dt(body["shift_start"])
    se = parse_dt(body["shift_end"])
    if se <= ss:
        raise ApiError(ERR_VALIDATION, "shift_end must be later than shift_start", 400)
    a = stamp_common({
        "aid_station_id": s["id"],
        "volunteer_id": body["volunteer_id"],
        "shift_start": body["shift_start"],
        "shift_end": body["shift_end"],
        "status": "OFFERED",
    })
    db.volunteer_assignments[a["id"]] = a
    return success_object(a, status=201)


@bp.get("/aid-stations/<sid>/assignments")
def list_assignments(sid):
    require_roles(*ALL)
    s = get_station_or_404(sid)
    items = [a for a in db.volunteer_assignments.values() if a["aid_station_id"] == s["id"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_list(page, limit, offset, total)


@bp.get("/volunteer-assignments/<aid>")
def get_assignment(aid):
    require_roles(*ALL)
    return success_object(get_assignment_or_404(aid))


@bp.post("/volunteer-assignments/<aid>/confirm")
def confirm_assignment(aid):
    require_roles("VolunteerCoordinator")
    a = get_assignment_or_404(aid)
    if a["status"] != "OFFERED":
        raise ApiError(ERR_INVALID_STATE, f"cannot confirm from {a['status']}", 409)
    my_start = parse_dt(a["shift_start"])
    my_end = parse_dt(a["shift_end"])
    for other in db.volunteer_assignments.values():
        if other["id"] == a["id"]:
            continue
        if other["volunteer_id"] != a["volunteer_id"] or other["status"] != "CONFIRMED":
            continue
        o_start = parse_dt(other["shift_start"])
        o_end = parse_dt(other["shift_end"])
        if my_start < o_end and o_start < my_end:
            raise ApiError(ERR_SHIFT_OVERLAP, "shift overlaps another confirmed shift", 409)
    a["status"] = "CONFIRMED"
    touch(a)
    station = db.aid_stations[a["aid_station_id"]]
    recompute_readiness(station)
    touch(station)
    return success_object(a)


@bp.post("/volunteer-assignments/<aid>/decline")
def decline_assignment(aid):
    require_roles("VolunteerCoordinator")
    a = get_assignment_or_404(aid)
    if a["status"] != "OFFERED":
        raise ApiError(ERR_INVALID_STATE, f"cannot decline from {a['status']}", 409)
    a["status"] = "DECLINED"
    touch(a)
    return success_object(a)


@bp.post("/volunteer-assignments/<aid>/no-show")
def no_show_assignment(aid):
    require_roles("VolunteerCoordinator")
    a = get_assignment_or_404(aid)
    if a["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE, f"cannot mark no-show from {a['status']}", 409)
    a["status"] = "NO_SHOW"
    touch(a)
    station = db.aid_stations[a["aid_station_id"]]
    recompute_readiness(station)
    touch(station)
    return success_object(a)
