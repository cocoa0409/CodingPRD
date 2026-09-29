"""Reference data (jurisdictions, lots, rides, workers) and the logical clock."""

import re

from flask import Blueprint, request

import db
import errors
import serializers as ser
import validators as v
from errors import fail, invalid
from middleware import (ROLE_COMPLIANCE_CLERK, ROLE_CREW_CHIEF,
                        ROLE_GENERAL_MANAGER, ROLE_LOT_BOSS,
                        ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER,
                        ROLE_SAFETY_OFFICER, ROLE_TICKETING_AUDITOR,
                        require_role)
from response import created, ok, paginate

bp = Blueprint("reference", __name__)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
LOT_SURFACES = ("PAVED", "GRAVEL", "GRASS")
RIDE_CLASSES = ("MAJOR", "FLAT", "KIDDIE")
EMPLOYMENT_TYPES = ("PERMANENT", "SEASONAL_DOMESTIC", "H2B_VISA")


# --------------------------------------------------------------------------
# jurisdictions
# --------------------------------------------------------------------------
@bp.post("/jurisdictions")
def create_jurisdiction():
    require_role(ROLE_PLATFORM_ADMIN)
    body = v.get_body()
    state_code = v.req_str(body, "state_code")
    if not STATE_CODE_RE.match(state_code):
        invalid("state_code must be exactly two uppercase letters.")
    name = v.req_str(body, "name")
    permit_lead_days = v.req_int(body, "permit_lead_days", minimum=0)
    amusement_tax_pct = v.req_num(body, "amusement_tax_pct", minimum=0, maximum=25,
                                 max_decimals=2)
    permit_fee_cents = v.req_int(body, "permit_fee_cents", minimum=0)
    requires_inspection = v.opt_bool(body, "requires_state_ride_inspection", False)
    slot_capacity = v.opt_int(body, "inspection_slot_capacity_per_day", 2, minimum=1)
    max_days = v.opt_int(body, "max_consecutive_work_days", 6, minimum=1)
    housing_permit = v.opt_bool(body, "housing_permit_required", False)

    for existing in db.store.jurisdictions.values():
        if existing["state_code"] == state_code:
            fail(errors.ERR_DUPLICATE_JURISDICTION_STATE,
                 "A jurisdiction with this state_code already exists.")

    row = db.create(db.store.jurisdictions, {
        "state_code": state_code,
        "name": name,
        "permit_lead_days": permit_lead_days,
        "amusement_tax_pct": amusement_tax_pct,
        "permit_fee_cents": permit_fee_cents,
        "requires_state_ride_inspection": requires_inspection,
        "inspection_slot_capacity_per_day": slot_capacity,
        "max_consecutive_work_days": max_days,
        "housing_permit_required": housing_permit,
    })
    return created(ser.jurisdiction(row))


@bp.get("/jurisdictions/<jurisdiction_id>")
def get_jurisdiction(jurisdiction_id):
    require_role(ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER, ROLE_GENERAL_MANAGER,
                 ROLE_TICKETING_AUDITOR, ROLE_COMPLIANCE_CLERK)
    row = v.path_jurisdiction(jurisdiction_id)
    return ok(ser.jurisdiction(row))


# --------------------------------------------------------------------------
# venues
# --------------------------------------------------------------------------
@bp.post("/venues")
def create_venue():
    require_role(ROLE_PLATFORM_ADMIN)
    body = v.get_body()
    jurisdiction = v.body_ref(body, "jurisdiction_id", "jurisdictions")
    if jurisdiction is None:
        v.req_str(body, "jurisdiction_id")
    name = v.req_str(body, "name")
    city = v.req_str(body, "city")
    lot_area_sqft = v.req_int(body, "lot_area_sqft", minimum=1)
    power_amps_available = v.req_int(body, "power_amps_available", minimum=1)
    expected_attendance = v.req_int(body, "expected_attendance", minimum=0)
    lot_surface = v.req_enum(body, "lot_surface", LOT_SURFACES)
    housing_pads = v.opt_int(body, "housing_pads_available", 0, minimum=0)

    row = db.create(db.store.venues, {
        "jurisdiction_id": jurisdiction["id"],
        "name": name,
        "city": city,
        "lot_area_sqft": lot_area_sqft,
        "power_amps_available": power_amps_available,
        "expected_attendance": expected_attendance,
        "lot_surface": lot_surface,
        "housing_pads_available": housing_pads,
    })
    return created(ser.venue(row))


@bp.get("/venues/<venue_id>")
def get_venue(venue_id):
    require_role(ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER, ROLE_GENERAL_MANAGER,
                 ROLE_TICKETING_AUDITOR, ROLE_LOT_BOSS)
    return ok(ser.venue(v.path_venue(venue_id)))


@bp.get("/venues")
def list_venues():
    require_role(ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER, ROLE_GENERAL_MANAGER,
                 ROLE_TICKETING_AUDITOR, ROLE_LOT_BOSS)
    jurisdiction_id = request.args.get("jurisdiction_id")
    state_code = request.args.get("state_code")
    rows = db.all_of(db.store.venues)
    if jurisdiction_id:
        rows = [r for r in rows if r["jurisdiction_id"] == jurisdiction_id]
    if state_code:
        allowed = set(j["id"] for j in db.store.jurisdictions.values()
                      if j["state_code"] == state_code)
        rows = [r for r in rows if r["jurisdiction_id"] in allowed]
    return paginate(rows, ser.venue)


# --------------------------------------------------------------------------
# rides
# --------------------------------------------------------------------------
@bp.post("/rides")
def create_ride():
    require_role(ROLE_PLATFORM_ADMIN)
    body = v.get_body()
    name = v.req_str(body, "name")
    ride_class = v.req_enum(body, "ride_class", RIDE_CLASSES)
    footprint_sqft = v.req_int(body, "footprint_sqft", minimum=1)
    power_amps = v.req_int(body, "power_amps", minimum=1)
    crew_size_setup = v.req_int(body, "crew_size_setup", minimum=1)
    setup_hours = v.req_num(body, "setup_hours")
    if v.dec(setup_hours) <= 0:
        invalid("setup_hours must be greater than zero.")
    axle_count = v.req_int(body, "axle_count", minimum=1)
    requires_inspection = v.opt_bool(body, "requires_state_inspection", True)

    row = db.create(db.store.rides, {
        "name": name,
        "ride_class": ride_class,
        "footprint_sqft": footprint_sqft,
        "power_amps": power_amps,
        "crew_size_setup": crew_size_setup,
        "setup_hours": setup_hours,
        "axle_count": axle_count,
        "requires_state_inspection": requires_inspection,
        "status": "AVAILABLE",
    })
    return created(ser.ride(row))


@bp.get("/rides/<ride_id>")
def get_ride(ride_id):
    require_role(ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER, ROLE_GENERAL_MANAGER,
                 ROLE_TICKETING_AUDITOR, ROLE_LOT_BOSS, ROLE_SAFETY_OFFICER)
    return ok(ser.ride(v.path_ride(ride_id)))


# --------------------------------------------------------------------------
# workers
# --------------------------------------------------------------------------
@bp.post("/workers")
def create_worker():
    require_role(ROLE_PLATFORM_ADMIN)
    body = v.get_body()
    full_name = v.req_str(body, "full_name")
    employment_type = v.req_enum(body, "employment_type", EMPLOYMENT_TYPES)
    hourly_rate_cents = v.req_int(body, "hourly_rate_cents", minimum=1)
    visa_raw, _ = v.opt_dt(body, "visa_expires_on")
    if employment_type == "H2B_VISA" and visa_raw is None:
        invalid("visa_expires_on is required when employment_type is H2B_VISA.")
    if employment_type != "H2B_VISA" and visa_raw is not None:
        invalid("visa_expires_on must be null unless employment_type is H2B_VISA.")
    certified = v.opt_str_list(body, "certified_ride_classes", RIDE_CLASSES, [])
    housing_required = v.opt_bool(body, "housing_required", False)

    row = db.create(db.store.workers, {
        "full_name": full_name,
        "employment_type": employment_type,
        "visa_expires_on": visa_raw,
        "hourly_rate_cents": hourly_rate_cents,
        "certified_ride_classes": certified,
        "housing_required": housing_required,
    })
    return created(ser.worker(row))


@bp.get("/workers/<worker_id>")
def get_worker(worker_id):
    require_role(ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER, ROLE_GENERAL_MANAGER,
                 ROLE_TICKETING_AUDITOR, ROLE_LOT_BOSS, ROLE_CREW_CHIEF)
    row = v.path_row("workers", worker_id)
    return ok(ser.worker(row))


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    require_role(ROLE_PLATFORM_ADMIN)
    body = v.get_body()
    raw, parsed = v.req_dt(body, "to_iso8601")
    db.set_clock(parsed)
    return ok({"current_utc": raw})
