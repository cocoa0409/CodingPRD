from datetime import timedelta

from flask import Blueprint, request

from db import db, common_create_fields, touch
from errors import ApiError
from middleware import get_identity, require_role
from response import success, list_response
from services import serialize
from services.common import (
    get_body, require_fields, parse_iso,
    get_visit, get_technician, get_assignment,
    get_pagination, paginate, sorted_by_creation,
)
from services.domain import release_assignment

bp = Blueprint("crew", __name__)


@bp.post("/crew-assignments")
def create_assignment():
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    body = get_body()
    require_fields(body, ["visit_id", "technician_id", "window_start_utc"])
    # Existence left-to-right.
    visit = get_visit(body["visit_id"])
    tech = get_technician(body["technician_id"])
    start = parse_iso(body["window_start_utc"], "window_start_utc")

    prop = db.properties.get(visit["property_id"])
    route = db.routes.get(visit["route_id"])
    duration = visit["duration_minutes"]
    end = start + timedelta(minutes=duration)

    # Safety: ladder cert >= property stories (priority 11, at reserve).
    if tech["ladder_cert_max_stories"] < prop["stories"]:
        raise ApiError("ERR_TECH_NOT_ASSIGNABLE", "Technician ladder cert below property stories")

    # Double-booking: half-open [start,end) padded by route travel buffer,
    # against the tech's existing RESERVED/CONFIRMED intervals (priority 12).
    buffer = timedelta(minutes=route["travel_buffer_minutes"]) if route else timedelta()
    new_start = start - buffer
    new_end = end + buffer
    for a in db.crew_assignments.values():
        if a["technician_id"] != tech["id"]:
            continue
        if a["status"] not in ("RESERVED", "CONFIRMED"):
            continue
        a_start = parse_iso(a["window_start_utc"], "window_start_utc")
        a_end = a_start + timedelta(minutes=a["duration_minutes"])
        # Half-open overlap test: [new_start,new_end) vs [a_start,a_end)
        if new_start < a_end and a_start < new_end:
            raise ApiError("ERR_TECH_DOUBLE_BOOKED", "Technician interval overlaps an existing assignment")

    a = common_create_fields()
    a.update({
        "visit_id": visit["id"],
        "technician_id": tech["id"],
        "window_start_utc": body["window_start_utc"],
        "duration_minutes": duration,
        "status": "RESERVED",
    })
    db.crew_assignments[a["id"]] = a
    # Reserve increments tech scheduled_minutes.
    tech["scheduled_minutes"] = tech["scheduled_minutes"] + duration
    touch(tech)
    return success(serialize.assignment_view(a), 201)


@bp.get("/crew-assignments")
def list_assignments():
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    visit_id = request.args.get("visit_id")
    technician_id = request.args.get("technician_id")
    status = request.args.get("status")
    limit, offset = get_pagination()
    items = []
    for a in db.crew_assignments.values():
        if visit_id is not None and a["visit_id"] != visit_id:
            continue
        if technician_id is not None and a["technician_id"] != technician_id:
            continue
        if status is not None and a["status"] != status:
            continue
        items.append(a)
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return list_response([serialize.assignment_view(a) for a in page], limit, offset, total)


@bp.get("/crew-assignments/<aid>")
def get_one_assignment(aid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    a = get_assignment(aid)
    return success(serialize.assignment_view(a), 200)


@bp.post("/crew-assignments/<aid>/confirm")
def confirm_assignment(aid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    a = get_assignment(aid)
    if a["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", "Only a RESERVED assignment can be confirmed")
    tech = db.technicians.get(a["technician_id"])
    visit = db.visits.get(a["visit_id"])
    prop = db.properties.get(visit["property_id"]) if visit else None
    # Re-check assignability: insurance ACTIVE AND ladder cert >= stories.
    if tech is None or tech["insurance_status"] != "ACTIVE":
        raise ApiError("ERR_TECH_NOT_ASSIGNABLE", "Technician insurance is not ACTIVE")
    if prop is not None and tech["ladder_cert_max_stories"] < prop["stories"]:
        raise ApiError("ERR_TECH_NOT_ASSIGNABLE", "Technician ladder cert below property stories")
    a["status"] = "CONFIRMED"
    touch(a)
    return success(serialize.assignment_view(a), 200)


@bp.post("/crew-assignments/<aid>/release")
def release_assignment_endpoint(aid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    a = get_assignment(aid)
    if a["status"] not in ("RESERVED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", "Only a RESERVED/CONFIRMED assignment can be released")
    release_assignment(a)
    return success(serialize.assignment_view(a), 200)
