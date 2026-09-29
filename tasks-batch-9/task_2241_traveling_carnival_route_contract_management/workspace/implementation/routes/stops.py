"""Route stops: creation, the lot lifecycle and the readiness read."""

from flask import Blueprint, request

import calc
import db
import errors
import serializers as ser
import transitions
import validators as v
from errors import fail, invalid
from middleware import (ROLE_COMPLIANCE_CLERK, ROLE_GENERAL_MANAGER,
                        ROLE_LOT_BOSS, ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER,
                        ROLE_TICKETING_AUDITOR, require_role)
from response import created, ok, paginate

bp = Blueprint("stops", __name__)

READ_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER, ROLE_GENERAL_MANAGER,
              ROLE_TICKETING_AUDITOR, ROLE_LOT_BOSS, ROLE_COMPLIANCE_CLERK)


@bp.post("/route-stops")
def create_route_stop():
    require_role(ROLE_ROUTE_MANAGER)
    body = v.get_body()
    route = v.body_ref(body, "route_id", "routes")
    venue = v.body_ref(body, "venue_id", "venues")
    previous = v.body_ref(body, "previous_stop_id", "route_stops")
    if route is None:
        v.req_str(body, "route_id")
    if venue is None:
        v.req_str(body, "venue_id")

    load_in_raw, load_in = v.req_dt(body, "load_in_start")
    open_raw, open_dt = v.req_dt(body, "open_date")
    close_raw, close_dt = v.req_dt(body, "close_date")
    teardown_raw, teardown_dt = v.req_dt(body, "teardown_deadline")
    haul_miles = v.opt_int(body, "haul_miles_from_previous", 0, minimum=0)
    if previous is not None and previous["route_id"] != route["id"]:
        invalid("previous_stop_id must belong to the same route.")

    if route["status"] not in ("DRAFT", "SEQUENCED"):
        fail(errors.ERR_ROUTE_STATE_INVALID,
             "Stops may only be added while the route is DRAFT or SEQUENCED.")

    operating_days = calc.stop_operating_days(open_dt, close_dt)
    row = db.create(db.store.route_stops, {
        "route_id": route["id"],
        "venue_id": venue["id"],
        "previous_stop_id": previous["id"] if previous is not None else None,
        "sequence_index": 0,
        "haul_miles_from_previous": haul_miles,
        "travel_hours_from_previous": 0,
        "load_in_start": load_in_raw,
        "open_date": open_raw,
        "close_date": close_raw,
        "teardown_deadline": teardown_raw,
        "operating_days": operating_days,
        "scheduled_operating_hours": float(
            operating_days * calc.DAILY_OPERATING_HOURS),
        "status": "PLANNED",
        "compliance_posture": "PERMIT_HOLD",
    })
    if route["status"] == "SEQUENCED":
        calc.reset_sequencing(route)
    else:
        db.touch(route)
    return created(ser.route_stop(row))


@bp.get("/route-stops/<stop_id>")
def get_route_stop(stop_id):
    require_role(*READ_ROLES)
    return ok(ser.route_stop(v.path_row("route_stops", stop_id)))


@bp.get("/route-stops")
def list_route_stops():
    require_role(*READ_ROLES)
    rows = db.all_of(db.store.route_stops)
    route_id = request.args.get("route_id")
    venue_id = request.args.get("venue_id")
    previous_stop_id = request.args.get("previous_stop_id")
    status = request.args.get("status")
    if route_id:
        rows = [r for r in rows if r["route_id"] == route_id]
    if venue_id:
        rows = [r for r in rows if r["venue_id"] == venue_id]
    if previous_stop_id:
        rows = [r for r in rows if r["previous_stop_id"] == previous_stop_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser.route_stop)


@bp.post("/route-stops/<stop_id>/begin-setup")
def begin_setup(stop_id):
    require_role(ROLE_ROUTE_MANAGER, ROLE_LOT_BOSS)
    stop = v.path_row("route_stops", stop_id)
    if stop["status"] != "CONFIRMED":
        fail(errors.ERR_STOP_STATE_INVALID,
             "Setup may only begin from CONFIRMED.")
    transitions.expire_permits(stop)
    if db.now() < calc.dt(stop, "load_in_start"):
        fail(errors.ERR_LOAD_IN_NOT_OPEN, "Load-in has not opened yet.")
    if not calc.allocations_of_stop(stop["id"], ("COMMITTED", "INSPECTION_HELD")):
        fail(errors.ERR_NO_COMMITTED_RIDES,
             "The lot holds no committed ride.")
    _require_transport_permit(stop)
    stop["status"] = "SETUP"
    db.touch(stop)
    return ok(ser.route_stop(stop))


def _require_transport_permit(stop):
    load_in = calc.dt(stop, "load_in_start")
    teardown_deadline = calc.dt(stop, "teardown_deadline")
    expired_seen = False
    for permit in calc.permits_of_stop(stop["id"], permit_type="TRANSPORT"):
        covers = (calc.dt(permit, "valid_from") <= load_in
                  and calc.dt(permit, "valid_until") >= teardown_deadline)
        if permit["status"] == "APPROVED" and covers:
            return
        if permit["status"] == "EXPIRED":
            expired_seen = True
    if expired_seen:
        fail(errors.ERR_PERMIT_EXPIRED,
             "The TRANSPORT permit for this lot has expired.")
    fail(errors.ERR_PERMIT_NOT_APPROVED,
         "An APPROVED TRANSPORT permit covering the move is required.")


@bp.post("/route-stops/<stop_id>/open-gates")
def open_gates(stop_id):
    require_role(ROLE_ROUTE_MANAGER, ROLE_LOT_BOSS)
    stop = v.path_row("route_stops", stop_id)
    if stop["status"] != "SETUP":
        fail(errors.ERR_STOP_STATE_INVALID, "Gates may only open from SETUP.")
    transitions.expire_permits(stop)
    if not calc.inspections_ok(stop):
        fail(errors.ERR_INSPECTION_NOT_PASSED,
             "An allocation on this lot has no passed state inspection.")
    if db.now() < calc.dt(stop, "open_date"):
        fail(errors.ERR_GATES_BEFORE_OPEN_DATE,
             "The lot's open_date has not been reached.")
    contract = calc.executed_contract_of_stop(stop["id"])
    minimum = int(contract["ride_minimum_count"]) if contract else 0
    committed = len(calc.allocations_of_stop(stop["id"], ("COMMITTED",)))
    if committed < minimum:
        fail(errors.ERR_RIDE_MINIMUM_NOT_MET,
             "The lot has fewer committed rides than the deal's minimum.")
    if not calc.event_permit_ok(stop):
        if calc._event_permit_expired_exists(stop):
            fail(errors.ERR_PERMIT_EXPIRED,
                 "The EVENT permit for this lot has expired.")
        fail(errors.ERR_PERMIT_NOT_APPROVED,
             "An APPROVED EVENT permit covering the run is required.")
    if not calc.crew_coverage_ok(stop):
        fail(errors.ERR_CREW_COVERAGE_INSUFFICIENT,
             "The lot's crew coverage is insufficient.")
    transitions.open_gates(stop)
    return ok(ser.route_stop(stop))


@bp.post("/route-stops/<stop_id>/teardown")
def teardown(stop_id):
    require_role(ROLE_ROUTE_MANAGER, ROLE_LOT_BOSS)
    stop = v.path_row("route_stops", stop_id)
    if stop["status"] != "OPEN":
        fail(errors.ERR_STOP_STATE_INVALID, "Teardown may only begin from OPEN.")
    if db.now() < calc.dt(stop, "close_date"):
        fail(errors.ERR_TEARDOWN_BEFORE_CLOSE_DATE,
             "The lot's close_date has not been reached.")
    transitions.teardown(stop)
    return ok(ser.route_stop(stop))


@bp.post("/route-stops/<stop_id>/cancel")
def cancel_stop(stop_id):
    require_role(ROLE_ROUTE_MANAGER, ROLE_GENERAL_MANAGER)
    stop = v.path_row("route_stops", stop_id)
    for contract in calc.contracts_of_stop(stop["id"]):
        if calc.settlements_of_contract(contract["id"], ("FINAL",)):
            fail(errors.ERR_SETTLEMENT_ALREADY_FINAL,
                 "The money for this lot is already closed.")
    if stop["status"] not in ("PLANNED", "CONFIRMED", "SETUP", "OPEN"):
        fail(errors.ERR_STOP_STATE_INVALID,
             "Only a PLANNED, CONFIRMED, SETUP or OPEN lot may go dark.")
    transitions.cancel_stop(stop)
    return ok(ser.route_stop(stop))


@bp.get("/route-stops/<stop_id>/readiness")
def readiness(stop_id):
    require_role(*READ_ROLES)
    stop = v.path_row("route_stops", stop_id)
    return ok(ser.readiness(stop))
