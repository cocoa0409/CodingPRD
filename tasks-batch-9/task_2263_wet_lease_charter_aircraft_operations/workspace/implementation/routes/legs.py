"""Flight legs: scheduling, dispatch, completion, cancellation (PRD 3.6)."""

from flask import Blueprint, request

from db import db, new_row, touch, public
from errors import ApiError, bad_request
from middleware import (
    require, check_ownership, scope_for_lessee,
    LESSOR_OPS, LESSEE, MAINTENANCE_CONTROLLER, BILLING_ADMIN,
)
from response import object_response, pagination, paged
from routes.common import find_aircraft, find_lease, find_crew, find_leg, filtered
from services import calculations as C
from services import workflows as W
import validate as V

bp = Blueprint("legs", __name__)

LEG_CLASSES = ("REVENUE", "REPOSITIONING", "MAINTENANCE_FERRY")
CANCEL_REASONS = ("TECHNICAL", "COMMERCIAL", "WEATHER", "CREW",
                  "INSURANCE_LAPSE", "REGULATORY")


def qualified_for(crew_id, lease_id):
    for qual in db.crew_qualifications.values():
        if (qual["crew_member_id"] == crew_id and qual["lease_id"] == lease_id
                and qual["status"] == "QUALIFIED"):
            return True
    return False


def enforce_crew_safety(lease, aircraft, captain, first_officer, anchor,
                        candidate_minutes, exclude_leg_id=None):
    """PRD 2.8 step 10 — captain before first officer inside each exposure check."""
    pilots = (captain, first_officer)
    for crew in pilots:
        if crew["status"] != "ACTIVE":
            raise ApiError("ERR_CREW_NOT_TYPE_RATED")
        if aircraft["type_designator"] not in crew["type_ratings"]:
            raise ApiError("ERR_CREW_NOT_TYPE_RATED")

    all_legs = list(db.flight_legs.values())
    projected = []
    for crew in pilots:
        projected.append(C.projected_exposure(
            crew["id"], all_legs, anchor, candidate_minutes, exclude_leg_id))
    for duty, _block in projected:
        if duty > C.MAX_DUTY_MINUTES_7D:
            raise ApiError("ERR_CREW_DUTY_LIMIT_EXCEEDED")
    for _duty, block in projected:
        if block > C.MAX_BLOCK_MINUTES_28D:
            raise ApiError("ERR_CREW_BLOCK_LIMIT_EXCEEDED")
    for crew in pilots:
        if not qualified_for(crew["id"], lease["id"]):
            raise ApiError("ERR_CREW_NOT_QUALIFIED_FOR_LESSEE_PROCEDURES")


@bp.post("/wetlease/flight-legs")
def create_leg():
    require((LESSOR_OPS,))
    body = V.json_body()
    lease_id = V.req_str(body, "lease_id")
    aircraft_id = V.opt_str(body, "aircraft_id")
    captain_id = V.req_str(body, "captain_id")
    first_officer_id = V.req_str(body, "first_officer_id")
    origin_icao = V.req_icao(body, "origin_icao", 4)
    dest_icao = V.req_icao(body, "dest_icao", 4)
    leg_class = V.req_enum(body, "leg_class", LEG_CLASSES)
    out_raw, scheduled_out = V.req_datetime(body, "scheduled_out")
    in_raw, scheduled_in = V.req_datetime(body, "scheduled_in")
    if scheduled_in <= scheduled_out:
        raise bad_request("scheduled_in must be strictly after scheduled_out")

    if aircraft_id is not None:
        find_aircraft(aircraft_id)
    lease = find_lease(lease_id)
    if aircraft_id is None:
        aircraft_id = lease["primary_aircraft_id"]
    aircraft = find_aircraft(aircraft_id)
    captain = find_crew(captain_id)
    first_officer = find_crew(first_officer_id)

    lessee = db.lessees.get(lease["lessee_id"])
    if lessee is None or lessee["status"] != "ACTIVE":
        raise ApiError("ERR_LESSEE_SUSPENDED")
    if lease["status"] != "ACTIVE":
        raise ApiError("ERR_LEASE_INVALID_STATE")

    scheduled_block_minutes = C.floor_minutes(scheduled_in, scheduled_out)

    enforce_crew_safety(lease, aircraft, captain, first_officer,
                        scheduled_out, scheduled_block_minutes)

    term_start = C.date_from_iso(lease["term_start_date"])
    term_end = C.date_from_iso(lease["term_end_date"])
    if scheduled_out.date() < term_start or scheduled_in.date() > term_end:
        raise ApiError("ERR_LEG_OUTSIDE_LEASE_TERM")

    if C.occupancy_conflict(scheduled_out, scheduled_in,
                            W.legs_of_aircraft(aircraft_id)) is not None:
        raise ApiError("ERR_AIRCRAFT_SCHEDULE_CONFLICT")

    row = new_row()
    row.update({
        "lease_id": lease_id,
        "aircraft_id": aircraft_id,
        "captain_id": captain_id,
        "first_officer_id": first_officer_id,
        "origin_icao": origin_icao,
        "dest_icao": dest_icao,
        "leg_class": leg_class,
        "scheduled_out": out_raw,
        "scheduled_in": in_raw,
        "actual_out": None,
        "actual_in": None,
        "scheduled_block_minutes": scheduled_block_minutes,
        "block_minutes": 0,
        "billable_block_minutes": 0,
        "technical_delay_minutes": 0,
        "cancelling_party": None,
        "cancel_reason": None,
        "crew_requalification_required": False,
        "status": "SCHEDULED",
        "billing_state": "UNBILLED",
        "_scheduled_out": scheduled_out,
        "_scheduled_in": scheduled_in,
        "_actual_out": None,
        "_actual_in": None,
        "_was_provisionally_billed": False,
    })
    db.flight_legs[row["id"]] = row

    W.recompute_leg_crew(row)
    W.recompute_open_period_for_leg(row)
    return object_response(public(row), 201)


@bp.get("/wetlease/flight-legs/<leg_id>")
def get_leg(leg_id):
    actor = require((LESSOR_OPS, MAINTENANCE_CONTROLLER, BILLING_ADMIN, LESSEE))
    leg = find_leg(leg_id)
    check_ownership(actor, "leg", leg)
    return object_response(public(leg))


@bp.get("/wetlease/flight-legs")
def list_legs():
    actor = require((LESSOR_OPS, MAINTENANCE_CONTROLLER, BILLING_ADMIN, LESSEE))
    limit, offset = pagination(request.args)
    rows = filtered(list(db.flight_legs.values()), request.args, {
        "lease_id": "lease_id",
        "aircraft_id": "aircraft_id",
        "captain_id": "captain_id",
        "first_officer_id": "first_officer_id",
        "status": "status",
        "billing_state": "billing_state",
    })
    rows = scope_for_lessee(actor, "leg", rows)
    return paged(rows, limit, offset)


@bp.post("/wetlease/flight-legs/<leg_id>/dispatch")
def dispatch_leg(leg_id):
    require((LESSOR_OPS,))
    body = V.json_body()
    actual_out_raw, actual_out = V.req_datetime(body, "actual_out")
    leg = find_leg(leg_id)

    lease = db.leases.get(leg["lease_id"])
    if lease is None or lease["status"] != "ACTIVE":
        raise ApiError("ERR_LEASE_INVALID_STATE")
    if leg["status"] != "SCHEDULED":
        raise ApiError("ERR_LEG_INVALID_STATE")

    aircraft = db.aircraft.get(leg["aircraft_id"])
    if aircraft is None or aircraft["status"] != "ASSIGNED":
        raise ApiError("ERR_AIRCRAFT_UNAVAILABLE")

    captain = find_crew(leg["captain_id"])
    first_officer = find_crew(leg["first_officer_id"])
    enforce_crew_safety(lease, aircraft, captain, first_officer,
                        leg["_scheduled_out"], leg["scheduled_block_minutes"],
                        exclude_leg_id=leg["id"])

    if W.active_certificate_covering(lease["id"], actual_out,
                                     require_additional_insured=True) is None:
        raise ApiError("ERR_INSURANCE_COVERAGE_MISSING")

    leg["status"] = "DISPATCHED"
    leg["actual_out"] = actual_out_raw
    leg["_actual_out"] = actual_out
    touch(leg)
    W.recompute_open_period_for_leg(leg)
    return object_response(public(leg))


@bp.post("/wetlease/flight-legs/<leg_id>/complete")
def complete_leg(leg_id):
    require((LESSOR_OPS,))
    body = V.json_body()
    actual_in_raw, actual_in = V.req_datetime(body, "actual_in")
    technical_delay = V.opt_int(body, "technical_delay_minutes", default=0, minimum=0)
    leg = find_leg(leg_id)

    if leg["status"] != "DISPATCHED":
        raise ApiError("ERR_LEG_INVALID_STATE")
    if leg["_actual_out"] is None or actual_in <= leg["_actual_out"]:
        raise bad_request("actual_in must be strictly later than actual_out")

    block_minutes = C.floor_minutes(actual_in, leg["_actual_out"])
    leg["status"] = "COMPLETED"
    leg["actual_in"] = actual_in_raw
    leg["_actual_in"] = actual_in
    leg["technical_delay_minutes"] = technical_delay
    leg["block_minutes"] = block_minutes
    leg["billable_block_minutes"] = C.leg_billable_block_minutes(
        leg["leg_class"], block_minutes)
    touch(leg)

    aircraft = db.aircraft.get(leg["aircraft_id"])
    if aircraft is not None:
        delta = C.D(block_minutes) / C.D(60)
        aircraft["airframe_hours_total"] = C.money2(
            C.D(aircraft["airframe_hours_total"]) + delta)
        aircraft["hours_since_last_check"] = C.money2(
            C.D(aircraft["hours_since_last_check"]) + delta)
        aircraft["cycles_since_last_check"] = aircraft["cycles_since_last_check"] + 1
        touch(aircraft)

    W.recompute_leg_crew(leg)
    W.recompute_open_period_for_leg(leg)
    return object_response(public(leg))


@bp.post("/wetlease/flight-legs/<leg_id>/cancel")
def cancel_leg_endpoint(leg_id):
    require((LESSOR_OPS,))
    body = V.json_body()
    cancelling_party = V.req_enum(body, "cancelling_party", ("LESSEE", "LESSOR"))
    cancel_reason = V.req_enum(body, "cancel_reason", CANCEL_REASONS)
    leg = find_leg(leg_id)

    if leg["status"] not in ("SCHEDULED", "DISPATCHED"):
        raise ApiError("ERR_LEG_INVALID_STATE")

    if leg["status"] == "DISPATCHED" and cancel_reason == "WEATHER":
        status = "DIVERTED"
    elif cancelling_party == "LESSEE":
        status = "CANCELLED_LESSEE"
    else:
        status = "CANCELLED_LESSOR"

    W.cancel_leg(leg, cancelling_party, cancel_reason, status=status)
    return object_response(public(leg))
