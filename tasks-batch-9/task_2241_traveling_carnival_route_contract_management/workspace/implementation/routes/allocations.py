"""Ride allocations: the lot's footprint and power budget."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import db
import errors
import serializers as ser
import transitions
import validators as v
from errors import fail
from middleware import (ROLE_GENERAL_MANAGER, ROLE_LOT_BOSS, ROLE_PLATFORM_ADMIN,
                        ROLE_ROUTE_MANAGER, ROLE_SAFETY_OFFICER,
                        ROLE_TICKETING_AUDITOR, require_role)
from response import created, ok, paginate

bp = Blueprint("allocations", __name__)

READ_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER, ROLE_GENERAL_MANAGER,
              ROLE_TICKETING_AUDITOR, ROLE_LOT_BOSS, ROLE_SAFETY_OFFICER)


@bp.post("/ride-allocations")
def create_allocation():
    require_role(ROLE_LOT_BOSS)
    body = v.get_body()
    ride = v.body_ref(body, "ride_id", "rides")
    stop = v.body_ref(body, "route_stop_id", "route_stops")
    if ride is None:
        v.req_str(body, "ride_id")
    if stop is None:
        v.req_str(body, "route_stop_id")
    expected_version = v.req_int(body, "expected_route_stop_version")

    if expected_version != int(stop["version"]):
        fail(errors.ERR_STALE_ROUTE_STOP_VERSION,
             "The lot has changed since it was read.")
    if stop["status"] not in ("PLANNED", "CONFIRMED", "SETUP"):
        fail(errors.ERR_STOP_STATE_INVALID,
             "Rides may only be reserved while the lot is PLANNED, CONFIRMED or "
             "SETUP.")
    if ride["status"] == "OUT_OF_SERVICE":
        fail(errors.ERR_RIDE_OUT_OF_SERVICE,
             "An out-of-service unit cannot be booked.")

    occupation_start = calc.dt(stop, "load_in_start")
    occupation_end = calc.dt(stop, "teardown_deadline")
    if calc.ride_double_booked(ride, stop, occupation_start, occupation_end):
        fail(errors.ERR_RIDE_DOUBLE_BOOKED,
             "This unit is already committed to an overlapping or too-close lot.")

    footprint = calc.charged_footprint_sqft(ride)
    amps = calc.charged_power_amps(ride)
    venue = calc.venue_of(stop)
    used_sqft = calc.stop_allocated_sqft_used(stop["id"])
    used_amps = v.dec(calc.stop_power_amps_used(stop["id"]))
    if used_sqft + footprint > calc.usable_lot_sqft(venue):
        fail(errors.ERR_LOT_CAPACITY_EXCEEDED,
             "The lot's usable footprint would be exceeded.")
    if used_amps + v.dec(amps) > calc.allowed_amps(venue):
        fail(errors.ERR_LOT_POWER_EXCEEDED,
             "The lot's amperage budget would be exceeded.")

    row = db.create(db.store.ride_allocations, {
        "ride_id": ride["id"],
        "route_stop_id": stop["id"],
        "status": "RESERVED",
        "footprint_charged_sqft": footprint,
        "power_charged_amps": amps,
        "occupation_start": stop["load_in_start"],
        "occupation_end": stop["teardown_deadline"],
        "released_at": None,
    })
    db.touch(stop)
    return created(ser.ride_allocation(row))


@bp.get("/ride-allocations/<alloc_id>")
def get_allocation(alloc_id):
    require_role(*READ_ROLES)
    return ok(ser.ride_allocation(v.path_row("ride_allocations", alloc_id)))


@bp.get("/ride-allocations")
def list_allocations():
    require_role(*READ_ROLES)
    rows = db.all_of(db.store.ride_allocations)
    ride_id = request.args.get("ride_id")
    route_stop_id = request.args.get("route_stop_id")
    status = request.args.get("status")
    if ride_id:
        rows = [r for r in rows if r["ride_id"] == ride_id]
    if route_stop_id:
        rows = [r for r in rows if r["route_stop_id"] == route_stop_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser.ride_allocation)


@bp.post("/ride-allocations/<alloc_id>/commit")
def commit_allocation(alloc_id):
    require_role(ROLE_LOT_BOSS)
    alloc = v.path_row("ride_allocations", alloc_id)
    stop = calc.stop_of_allocation(alloc)
    if stop is None or stop["status"] not in ("CONFIRMED", "SETUP"):
        fail(errors.ERR_STOP_STATE_INVALID,
             "The lot must be CONFIRMED or SETUP to commit a ride.")
    if alloc["status"] != "RESERVED":
        fail(errors.ERR_ALLOCATION_STATE_INVALID,
             "Only a RESERVED allocation may be committed.")
    ride = db.store.rides.get(alloc["ride_id"])
    if ride is not None and ride["status"] == "OUT_OF_SERVICE":
        fail(errors.ERR_RIDE_OUT_OF_SERVICE,
             "An out-of-service unit cannot be committed.")
    transitions.commit_allocation(alloc, stop)
    db.touch(stop)
    return ok(ser.ride_allocation(alloc))


@bp.post("/ride-allocations/<alloc_id>/release")
def release_allocation(alloc_id):
    require_role(ROLE_LOT_BOSS, ROLE_ROUTE_MANAGER)
    alloc = v.path_row("ride_allocations", alloc_id)
    stop = calc.stop_of_allocation(alloc)
    if stop is None or stop["status"] == "CLOSED":
        fail(errors.ERR_STOP_STATE_INVALID,
             "An allocation of a CLOSED lot may not be released.")
    if alloc["status"] not in calc.ALLOC_ACTIVE:
        fail(errors.ERR_ALLOCATION_STATE_INVALID,
             "Only a non-terminal allocation may be released.")
    transitions.release_allocation(alloc, stop)
    return ok(ser.ride_allocation(alloc))


_ = Decimal
