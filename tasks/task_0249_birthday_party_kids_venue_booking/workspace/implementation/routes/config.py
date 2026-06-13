"""Configuration resources: Venue, Room, PartyPackage, StaffMember + the SystemClock.

VenueManager owns creation and lifecycle; all roles may read (GET).
"""

from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import err
from middleware import get_user_context, require_roles
from response import list_success, success
from services.common import (
    as_enum, as_int, as_number, as_string, parse_iso8601, iso_from_dt,
    paginate, parse_pagination, public_view, require_body, require_present,
    stamp_create, touch,
)

config_bp = Blueprint("config", __name__)

ALL_ROLES = {"VenueManager", "Coordinator", "FinanceClerk", "Guardian"}


# ============================================================================
# Venue
# ============================================================================

@config_bp.post("/venues")
def create_venue():
    _, role = get_user_context()
    require_roles(role, {"VenueManager"})
    body = require_body()
    name = as_string(require_present(body, "name"), "name")

    timezone_val = "UTC"
    if "timezone" in body and body["timezone"] is not None:
        timezone_val = as_string(body["timezone"], "timezone")

    weather_dependent = False
    if "weather_dependent" in body and body["weather_dependent"] is not None:
        from services.common import as_bool
        weather_dependent = as_bool(body["weather_dependent"], "weather_dependent")

    reschedule_lead_hours = 48
    if "reschedule_lead_hours" in body and body["reschedule_lead_hours"] is not None:
        reschedule_lead_hours = as_int(body["reschedule_lead_hours"], "reschedule_lead_hours")

    venue = {
        "name": name,
        "timezone": timezone_val,
        "weather_dependent": weather_dependent,
        "reschedule_lead_hours": reschedule_lead_hours,
        "status": "ACTIVE",
    }
    stamp_create(venue)
    db.venues[venue["id"]] = venue
    return success(public_view(venue), status=201)


@config_bp.get("/venues")
def list_venues():
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.venues.values())
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [v for v in items if v["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return list_success([public_view(v) for v in page], limit, offset, total)


@config_bp.get("/venues/<venue_id>")
def get_venue(venue_id):
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    v = db.venues.get(venue_id)
    if v is None:
        raise err("ERR_VENUE_NOT_FOUND", "Venue %s not found" % venue_id)
    return success(public_view(v))


# ============================================================================
# Room
# ============================================================================

@config_bp.post("/rooms")
def create_room():
    _, role = get_user_context()
    require_roles(role, {"VenueManager"})
    body = require_body()
    venue_id = as_string(require_present(body, "venue_id"), "venue_id")
    name = as_string(require_present(body, "name"), "name")
    max_capacity = as_int(require_present(body, "max_capacity"), "max_capacity")
    if max_capacity < 1:
        raise err("ERR_INVALID_REQUEST", "max_capacity must be >= 1")

    room_kind = "INDOOR"
    if "room_kind" in body and body["room_kind"] is not None:
        room_kind = as_enum(body["room_kind"], "room_kind", {"INDOOR", "OUTDOOR"})

    buffer_minutes = 30
    if "buffer_minutes" in body and body["buffer_minutes"] is not None:
        buffer_minutes = as_int(body["buffer_minutes"], "buffer_minutes")
        if buffer_minutes < 0:
            raise err("ERR_INVALID_REQUEST", "buffer_minutes must be >= 0")

    if venue_id not in db.venues:
        raise err("ERR_VENUE_NOT_FOUND", "Venue %s not found" % venue_id)

    room = {
        "venue_id": venue_id,
        "name": name,
        "room_kind": room_kind,
        "max_capacity": max_capacity,
        "buffer_minutes": buffer_minutes,
        "status": "OPEN",
    }
    stamp_create(room)
    db.rooms[room["id"]] = room
    return success(public_view(room), status=201)


@config_bp.get("/rooms")
def list_rooms():
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.rooms.values())
    venue_id = request.args.get("venue_id")
    if venue_id is not None:
        items = [r for r in items if r["venue_id"] == venue_id]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [r for r in items if r["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return list_success([public_view(r) for r in page], limit, offset, total)


@config_bp.get("/rooms/<room_id>")
def get_room(room_id):
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    r = db.rooms.get(room_id)
    if r is None:
        raise err("ERR_ROOM_NOT_FOUND", "Room %s not found" % room_id)
    return success(public_view(r))


@config_bp.post("/rooms/<room_id>/close")
def close_room(room_id):
    _, role = get_user_context()
    require_roles(role, {"VenueManager"})
    r = db.rooms.get(room_id)
    if r is None:
        raise err("ERR_ROOM_NOT_FOUND", "Room %s not found" % room_id)
    r["status"] = "CLOSED"
    touch(r)
    return success(public_view(r))


# ============================================================================
# PartyPackage
# ============================================================================

@config_bp.post("/packages")
def create_package():
    _, role = get_user_context()
    require_roles(role, {"VenueManager"})
    body = require_body()
    venue_id = as_string(require_present(body, "venue_id"), "venue_id")
    theme = as_string(require_present(body, "theme"), "theme")
    base_price_cents = as_int(require_present(body, "base_price_cents"), "base_price_cents")
    if base_price_cents < 0:
        raise err("ERR_INVALID_REQUEST", "base_price_cents must be >= 0")
    included_children = as_int(require_present(body, "included_children"), "included_children")
    if included_children < 1:
        raise err("ERR_INVALID_REQUEST", "included_children must be >= 1")
    per_extra_child_cents = as_int(require_present(body, "per_extra_child_cents"), "per_extra_child_cents")
    if per_extra_child_cents < 0:
        raise err("ERR_INVALID_REQUEST", "per_extra_child_cents must be >= 0")

    base_duration_minutes = 120
    if "base_duration_minutes" in body and body["base_duration_minutes"] is not None:
        base_duration_minutes = as_int(body["base_duration_minutes"], "base_duration_minutes")
        if base_duration_minutes < 1:
            raise err("ERR_INVALID_REQUEST", "base_duration_minutes must be >= 1")

    deposit_pct = 0.25
    if "deposit_pct" in body and body["deposit_pct"] is not None:
        deposit_pct = as_number(body["deposit_pct"], "deposit_pct")
        if not (deposit_pct > 0 and deposit_pct <= 1):
            raise err("ERR_INVALID_REQUEST", "deposit_pct must be in (0, 1]")

    if venue_id not in db.venues:
        raise err("ERR_VENUE_NOT_FOUND", "Venue %s not found" % venue_id)

    pkg = {
        "venue_id": venue_id,
        "theme": theme,
        "base_price_cents": base_price_cents,
        "included_children": included_children,
        "per_extra_child_cents": per_extra_child_cents,
        "base_duration_minutes": base_duration_minutes,
        "deposit_pct": deposit_pct,
        "status": "LISTED",
    }
    stamp_create(pkg)
    db.packages[pkg["id"]] = pkg
    return success(public_view(pkg), status=201)


@config_bp.get("/packages")
def list_packages():
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.packages.values())
    venue_id = request.args.get("venue_id")
    if venue_id is not None:
        items = [p for p in items if p["venue_id"] == venue_id]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [p for p in items if p["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return list_success([public_view(p) for p in page], limit, offset, total)


@config_bp.get("/packages/<package_id>")
def get_package(package_id):
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    p = db.packages.get(package_id)
    if p is None:
        raise err("ERR_PACKAGE_NOT_FOUND", "Package %s not found" % package_id)
    return success(public_view(p))


@config_bp.post("/packages/<package_id>/retire")
def retire_package(package_id):
    _, role = get_user_context()
    require_roles(role, {"VenueManager"})
    p = db.packages.get(package_id)
    if p is None:
        raise err("ERR_PACKAGE_NOT_FOUND", "Package %s not found" % package_id)
    p["status"] = "RETIRED"
    touch(p)
    return success(public_view(p))


# ============================================================================
# StaffMember
# ============================================================================

@config_bp.post("/staff-members")
def create_staff():
    _, role = get_user_context()
    require_roles(role, {"VenueManager"})
    body = require_body()
    venue_id = as_string(require_present(body, "venue_id"), "venue_id")
    full_name = as_string(require_present(body, "full_name"), "full_name")

    skills = []
    if "skills" in body and body["skills"] is not None:
        raw = body["skills"]
        if not isinstance(raw, list):
            raise err("ERR_INVALID_REQUEST", "skills must be an array")
        for s in raw:
            as_enum(s, "skills", {"HOST", "ENTERTAINER", "COOK"})
        skills = list(raw)

    if venue_id not in db.venues:
        raise err("ERR_VENUE_NOT_FOUND", "Venue %s not found" % venue_id)

    staff = {
        "venue_id": venue_id,
        "full_name": full_name,
        "skills": skills,
        "status": "AVAILABLE",
    }
    stamp_create(staff)
    db.staff_members[staff["id"]] = staff
    return success(public_view(staff), status=201)


@config_bp.get("/staff-members")
def list_staff():
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.staff_members.values())
    venue_id = request.args.get("venue_id")
    if venue_id is not None:
        items = [s for s in items if s["venue_id"] == venue_id]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [s for s in items if s["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return list_success([public_view(s) for s in page], limit, offset, total)


@config_bp.get("/staff-members/<staff_id>")
def get_staff(staff_id):
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    s = db.staff_members.get(staff_id)
    if s is None:
        raise err("ERR_STAFF_NOT_FOUND", "Staff member %s not found" % staff_id)
    return success(public_view(s))


@config_bp.post("/staff-members/<staff_id>/deactivate")
def deactivate_staff(staff_id):
    _, role = get_user_context()
    require_roles(role, {"VenueManager"})
    s = db.staff_members.get(staff_id)
    if s is None:
        raise err("ERR_STAFF_NOT_FOUND", "Staff member %s not found" % staff_id)
    s["status"] = "INACTIVE"
    touch(s)
    return success(public_view(s))


# ============================================================================
# SystemClock (test-driving)
# ============================================================================

@config_bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_user_context()
    require_roles(role, {"VenueManager", "Coordinator"})
    body = require_body()
    to_iso8601 = require_present(body, "to_iso8601")
    dt = parse_iso8601(to_iso8601, "to_iso8601")
    db.clock["current_utc"] = iso_from_dt(dt)
    return success(public_view(db.clock))


@config_bp.get("/_clock")
def get_clock():
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    return success(public_view(db.clock))
