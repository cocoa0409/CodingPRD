"""Site area and ground allocation endpoints."""

from flask import Blueprint, request

import db
import serializers
from errors import fail
from middleware import authenticate, get_allocation, get_area, get_event
from response import success
from services import cascades, derived
from services.common import new_record, paginate, touch
from services.derived import sorted_all
from util import HOURS_24, body, req_dt, req_enum, req_int, req_str

bp = Blueprint("areas", __name__)

AREA_KINDS = ("CAMP", "DEMO", "PARKING", "SUTLER", "SPECTATOR")
AREA_ROLES = ["EventOrganizer", "SafetyOfficer"]


@bp.post("/events/<event_id>/site-areas")
def create_site_area(event_id):
    authenticate(["EventOrganizer"], creation=True)
    ev = get_event(event_id)
    if ev["event_posture"] not in ("PLANNING", "REGISTRATION_OPEN", "PUBLISHED"):
        fail("ERR_INVALID_EVENT_POSTURE", "site areas require PLANNING, REGISTRATION_OPEN, or PUBLISHED")
    data = body(request)
    rec = new_record()
    rec.update(
        event_id=ev["id"],
        area_name=req_str(data, "area_name"),
        area_kind=req_enum(data, "area_kind", AREA_KINDS),
        capacity_units=req_int(data, "capacity_units", minimum=0),
        status="ACTIVE",
    )
    db.areas[rec["id"]] = rec
    return success(serializers.site_area(rec), 201)


@bp.get("/site-areas/<area_id>")
def read_site_area(area_id):
    authenticate(AREA_ROLES)
    return success(serializers.site_area(get_area(area_id)), 200)


@bp.get("/events/<event_id>/site-areas")
def list_site_areas(event_id):
    authenticate(AREA_ROLES)
    ev = get_event(event_id)
    items = [a for a in db.areas.values() if a["event_id"] == ev["id"]]
    kind = request.args.get("area_kind")
    if kind is not None:
        items = [a for a in items if a["area_kind"] == kind]
    page, meta = paginate(sorted_all(items))
    return success([serializers.site_area(a) for a in page], 200, pagination=meta)


@bp.post("/site-areas/<area_id>/close")
def close_site_area(area_id):
    authenticate(AREA_ROLES)
    a = get_area(area_id)
    if a["status"] != "ACTIVE":
        fail("ERR_AREA_NOT_ACTIVE", "only an ACTIVE area can be closed")
    a["status"] = "CLOSED"
    touch(a)
    return success(serializers.site_area(a), 200)


@bp.post("/site-areas/<area_id>/allocations")
def create_allocation(area_id):
    authenticate(["EventOrganizer"], creation=True)
    area = get_area(area_id)
    data = body(request)
    unit_id = data.get("unit_id")
    vendor_id = data.get("vendor_id")
    # Existence (priority 3) of body references.
    unit = None
    if unit_id is not None:
        unit = db.units.get(unit_id)
        if unit is None:
            fail("ERR_UNIT_NOT_FOUND", f"unit {unit_id} not found")
    vendor = None
    if vendor_id is not None:
        vendor = db.vendors.get(vendor_id)
        if vendor is None:
            fail("ERR_VENDOR_NOT_FOUND", f"vendor {vendor_id} not found")
    ev = db.events[area["event_id"]]
    # State (priority 5): posture, then area active.
    if ev["event_posture"] not in ("REGISTRATION_OPEN", "PUBLISHED", "EVENT_OPEN"):
        fail("ERR_INVALID_EVENT_POSTURE", "allocations require REGISTRATION_OPEN, PUBLISHED, or EVENT_OPEN")
    if area["status"] != "ACTIVE":
        fail("ERR_AREA_NOT_ACTIVE", "the site area is not ACTIVE")
    # Body shape + business constraints (priority 7, scaffold table order).
    starts_at = req_dt(data, "starts_at")
    ends_at = req_dt(data, "ends_at")
    units = req_int(data, "units", minimum=1)
    # Overlap against ACTIVE allocations on the same area (half-open; touching OK).
    for al in db.allocations.values():
        if al["site_area_id"] != area["id"] or al["status"] != "ACTIVE":
            continue
        if starts_at < al["ends_at"] and al["starts_at"] < ends_at:
            fail("ERR_ALLOCATION_OVERLAP", "allocation window overlaps an existing allocation")
    # Exactly one occupying party.
    if (unit_id is None) == (vendor_id is None):
        fail("ERR_ALLOCATION_PARTY_REQUIRED", "exactly one of unit_id / vendor_id is required")
    # Area-kind fitness: unit on CAMP, vendor on SUTLER.
    if unit_id is not None and area["area_kind"] != "CAMP":
        fail("ERR_AREA_KIND_MISMATCH", "a unit may occupy only CAMP ground")
    if vendor_id is not None and area["area_kind"] != "SUTLER":
        fail("ERR_AREA_KIND_MISMATCH", "a vendor may occupy only SUTLER row")
    # Party standing.
    if unit is not None and unit["status"] != "APPROVED":
        fail("ERR_INVALID_UNIT_STATUS", "the unit party must be APPROVED")
    if vendor is not None and vendor["status"] != "CONTRACTED":
        fail("ERR_INVALID_VENDOR_STATUS", "the vendor party must be CONTRACTED")
    # Temporal (priority 8): coherent range, then event window +/- 24h.
    if starts_at >= ends_at:
        fail("ERR_INVALID_TIME_RANGE", "starts_at must be strictly before ends_at")
    if starts_at < ev["event_starts_at"] - HOURS_24 or ends_at > ev["event_ends_at"] + HOURS_24:
        fail("ERR_OUTSIDE_EVENT_WINDOW", "allocation window exceeds the event window +/- 24h")
    # Capacity (priority 10), inclusive boundary.
    if derived.area_allocated_units(area) + units > area["capacity_units"]:
        fail("ERR_AREA_CAPACITY_EXCEEDED", "allocation would exceed area capacity")
    rec = new_record()
    rec.update(
        site_area_id=area["id"],
        unit_id=unit_id,
        vendor_id=vendor_id,
        starts_at=starts_at,
        ends_at=ends_at,
        units=units,
        status="ACTIVE",
    )
    db.allocations[rec["id"]] = rec
    return success(serializers.allocation(rec), 201)


@bp.get("/allocations")
def list_allocations():
    authenticate(AREA_ROLES)
    items = list(db.allocations.values())
    site_area_id = request.args.get("site_area_id")
    if site_area_id is not None:
        items = [a for a in items if a["site_area_id"] == site_area_id]
    unit_id = request.args.get("unit_id")
    if unit_id is not None:
        items = [a for a in items if a["unit_id"] == unit_id]
    vendor_id = request.args.get("vendor_id")
    if vendor_id is not None:
        items = [a for a in items if a["vendor_id"] == vendor_id]
    page, meta = paginate(sorted_all(items))
    return success([serializers.allocation(a) for a in page], 200, pagination=meta)


@bp.get("/allocations/<allocation_id>")
def read_allocation(allocation_id):
    authenticate(AREA_ROLES)
    return success(serializers.allocation(get_allocation(allocation_id)), 200)


@bp.post("/allocations/<allocation_id>/release")
def release_allocation(allocation_id):
    authenticate(["EventOrganizer"])
    al = get_allocation(allocation_id)
    if al["status"] != "ACTIVE":
        fail("ERR_VALIDATION", "only an ACTIVE allocation can be released")
    cascades.release_allocation(al)
    return success(serializers.allocation(al), 200)
