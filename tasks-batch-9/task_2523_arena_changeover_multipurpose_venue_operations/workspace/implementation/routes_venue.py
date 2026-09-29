"""Arena registration, house configuration profiles and anchor tenants."""

from flask import Blueprint

import calc
import serial
import validate as v
from envelope import created, ok, ok_list
from errors import ApiError
from store import db, ordered, stamp_new

bp = Blueprint("venues", __name__)

CONFIG_CODES = ("ICE_HOCKEY", "COURT_BASKETBALL", "CONCERT_END_STAGE",
                "CONCERT_IN_ROUND", "FAMILY_SHOW")
SEATING_MODES = ("FULL_BOWL", "RETRACTABLE_IN", "CURTAINED_HALF")
HOLD_TIERS = ("TIER_1", "TIER_2", "TIER_3")


def get_venue(venue_id):
    venue = db.venues.get(venue_id)
    if venue is None:
        raise ApiError("ERR_VENUE_NOT_FOUND")
    return venue


@bp.post("/venues")
def create_venue():
    v.auth(("VenueOperationsDirector",))
    payload = v.body()
    row = {
        "name": v.req_str(payload, "name", 1, 120),
        "rigging_capacity_kg": v.req_num(payload, "rigging_capacity_kg"),
        "dock_count": v.req_int(payload, "dock_count", 1, 8),
        "max_bowl_seats": v.req_int(payload, "max_bowl_seats", 1),
        "crew_headcount_cap": v.req_int(payload, "crew_headcount_cap", 1, 200),
        "min_turnaround_buffer_minutes": v.opt_int(
            payload, "min_turnaround_buffer_minutes", 45, 0, 240),
        "dock_buffer_minutes": v.opt_int(payload, "dock_buffer_minutes", 30, 0, 180),
        "overnight_shift_start_local_hour": v.opt_int(
            payload, "overnight_shift_start_local_hour", 22, 18, 23),
        "changeover_debt_minutes": 0,
    }
    if row["rigging_capacity_kg"] <= 0:
        v.bad("rigging_capacity_kg must be greater than 0.")
    if row["max_bowl_seats"] <= 0:
        v.bad("max_bowl_seats must be greater than 0.")
    stamp_new(row)
    db.venues[row["id"]] = row
    return created(serial.venue(row))


@bp.get("/venues/<venue_id>")
def read_venue(venue_id):
    v.auth(v.ALL_ROLES)
    return ok(serial.venue(get_venue(venue_id)))


@bp.post("/venues/<venue_id>/configuration-profiles")
def create_profile(venue_id):
    v.auth(("VenueOperationsDirector",))
    payload = v.body()
    fields = {
        "code": v.req_enum(payload, "code", CONFIG_CODES),
        "requires_ice": v.req_bool(payload, "requires_ice"),
        "ice_cover_required": v.req_bool(payload, "ice_cover_required"),
        "seating_mode": v.req_enum(payload, "seating_mode", SEATING_MODES),
        "nominal_seats": v.req_int(payload, "nominal_seats", 1),
        "base_changeover_minutes": v.req_int(payload, "base_changeover_minutes", 30, 1440),
        "crew_size_required": v.req_int(payload, "crew_size_required", 1, 200),
        "floor_protection_panels_required": v.req_int(
            payload, "floor_protection_panels_required", 0, 2000),
        "dehumidification_required_lph": v.req_num(payload, "dehumidification_required_lph", 0),
        "rigging_points_required": v.req_int(payload, "rigging_points_required", 0, 400),
    }
    venue = get_venue(venue_id)
    fields["venue_id"] = venue["id"]
    stamp_new(fields, with_version=False)
    db.profiles[fields["id"]] = fields
    return created(serial.profile(fields))


@bp.get("/venues/<venue_id>/configuration-profiles")
def list_profiles(venue_id):
    v.auth(v.ALL_ROLES)
    limit, offset = v.pagination()
    venue = get_venue(venue_id)
    code = v.filter_arg("code")
    matched = [p for p in db.profiles.values() if p["venue_id"] == venue["id"]]
    if code is not None:
        matched = [p for p in matched if p["code"] == code]
    matched = ordered(matched)
    page, total = v.paginate(matched, limit, offset)
    return ok_list([serial.profile(p) for p in page], limit, offset, total)


@bp.post("/venues/<venue_id>/anchor-tenants")
def create_tenant(venue_id):
    v.auth(("VenueOperationsDirector",))
    payload = v.body()
    fields = {
        "name": v.req_str(payload, "name", 1, 120),
        "hold_priority_tier": v.req_enum(payload, "hold_priority_tier", HOLD_TIERS),
        "guaranteed_holds_per_season": v.req_int(
            payload, "guaranteed_holds_per_season", 1, 60),
    }
    venue = get_venue(venue_id)
    fields["venue_id"] = venue["id"]
    fields["challenge_credits"] = calc.CHALLENGE_CREDIT_GRANT
    stamp_new(fields)
    db.tenants[fields["id"]] = fields
    return created(serial.tenant(fields))


@bp.get("/venues/<venue_id>/anchor-tenants")
def list_tenants(venue_id):
    v.auth(v.ALL_ROLES)
    limit, offset = v.pagination()
    venue = get_venue(venue_id)
    tier = v.filter_arg("hold_priority_tier")
    matched = [t for t in db.tenants.values() if t["venue_id"] == venue["id"]]
    if tier is not None:
        matched = [t for t in matched if t["hold_priority_tier"] == tier]
    matched = ordered(matched)
    page, total = v.paginate(matched, limit, offset)
    return ok_list([serial.tenant(t) for t in page], limit, offset, total)
