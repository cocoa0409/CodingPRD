"""FlightLeg endpoints plus tankering-directive proposal (PRD 3.8)."""

from flask import Blueprint, g

import calc
import domain
import fetch
import serializers as ser
import validators as v
from db import db, rows_in_order
from errors import fail
from middleware import (FUEL_ANALYST, FUEL_OPS_CONTROLLER, RISK_POLICY_ADMIN,
                        STATION_COORDINATOR, endpoint, new_row, touch)
from response import created, ok, ok_list

bp = Blueprint("legs", __name__)

DIRECTIVE_STATUSES = ("PROPOSED", "NEEDS_REVISION", "APPROVED", "REJECTED",
                      "EXECUTED", "RECONCILED", "SUPERSEDED")


@bp.post("/fuel/flight-legs")
@endpoint(FUEL_OPS_CONTROLLER, FUEL_ANALYST)
def create_leg():
    data = v.body()
    flight_number = v.get_string(data, "flight_number", min_len=1, max_len=8)
    departure_date = v.get_date(data, "departure_date")
    origin_id = v.get_string(data, "origin_station_id", min_len=1)
    destination_id = v.get_string(data, "destination_station_id", min_len=1)
    fleet_type = v.get_enum(data, "fleet_type", calc.FLEET_TYPES)
    block_minutes = v.get_int(data, "planned_block_minutes", exclusive_minimum=0)
    planned_burn = v.get_number(data, "planned_burn_gallons", exclusive_minimum=0)
    tank_capacity = v.get_number(data, "tank_capacity_gallons")
    payload = v.get_number(data, "payload_lbs", exclusive_minimum=0)
    max_payload = v.get_number(data, "max_takeoff_payload_lbs")
    landing_weight = v.get_number(data, "landing_weight_lbs", exclusive_minimum=0)
    max_landing_weight = v.get_number(data, "max_landing_weight_lbs")

    if destination_id == origin_id:
        fail("ERR_INVALID_REQUEST",
             "destination_station_id must differ from origin_station_id.")
    if tank_capacity <= planned_burn:
        fail("ERR_INVALID_REQUEST",
             "tank_capacity_gallons must be strictly greater than planned_burn_gallons.")
    if max_payload <= payload:
        fail("ERR_INVALID_REQUEST",
             "max_takeoff_payload_lbs must be strictly greater than payload_lbs.")
    if max_landing_weight < landing_weight:
        fail("ERR_INVALID_REQUEST",
             "max_landing_weight_lbs must be at least landing_weight_lbs.")

    origin = fetch.station(origin_id)
    destination = fetch.station(destination_id)

    for row in db.legs.values():
        if row["flight_number"] == flight_number \
                and row["departure_date"] == departure_date:
            fail("ERR_DUPLICATE_FLIGHT_LEG",
                 "A leg already exists for flight %s on %s."
                 % (flight_number, departure_date))

    row = new_row()
    row.update({
        "flight_number": flight_number,
        "departure_date": departure_date,
        "origin_station_id": origin["id"],
        "destination_station_id": destination["id"],
        "fleet_type": fleet_type,
        "planned_block_minutes": block_minutes,
        "planned_burn_gallons": planned_burn,
        "tank_capacity_gallons": tank_capacity,
        "payload_lbs": payload,
        "max_takeoff_payload_lbs": max_payload,
        "landing_weight_lbs": landing_weight,
        "max_landing_weight_lbs": max_landing_weight,
        "actual_block_minutes": None,
        "actual_uplift_gallons": None,
    })
    db.legs[row["id"]] = row
    return created(ser.flight_leg(row))


@bp.get("/fuel/flight-legs/<leg_id>")
@endpoint(RISK_POLICY_ADMIN, FUEL_ANALYST, FUEL_OPS_CONTROLLER, STATION_COORDINATOR)
def read_leg(leg_id):
    return ok(ser.flight_leg(fetch.flight_leg(leg_id)))


@bp.get("/fuel/flight-legs")
@endpoint(RISK_POLICY_ADMIN, FUEL_ANALYST, FUEL_OPS_CONTROLLER, STATION_COORDINATOR)
def list_legs():
    limit, offset = v.pagination()
    origin_id = v.raw_filter("origin_station_id")
    destination_id = v.raw_filter("destination_station_id")
    departure_date = v.date_filter("departure_date")
    fleet_type = v.enum_filter("fleet_type", calc.FLEET_TYPES)

    rows = rows_in_order(db.legs)
    rows.sort(key=lambda r: (r["departure_date"], r["_seq"]))
    if origin_id is not None:
        rows = [r for r in rows if r["origin_station_id"] == origin_id]
    if destination_id is not None:
        rows = [r for r in rows if r["destination_station_id"] == destination_id]
    if departure_date is not None:
        rows = [r for r in rows if r["departure_date"] == departure_date]
    if fleet_type is not None:
        rows = [r for r in rows if r["fleet_type"] == fleet_type]
    page, total = v.paginate(rows, limit, offset)
    return ok_list([ser.flight_leg(r) for r in page], limit, offset, total)


@bp.post("/fuel/flight-legs/<leg_id>/tankering-directives")
@endpoint(FUEL_ANALYST)
def create_directive(leg_id):
    data = v.body()
    uplift = v.get_number(data, "requested_uplift_gallons")
    expected = v.get_int(data, "expected_flight_leg_version")

    leg = fetch.flight_leg(leg_id)

    if expected != leg["version"]:
        fail("ERR_STALE_VERSION",
             "expected_flight_leg_version %s does not match current version %s."
             % (expected, leg["version"]))

    if uplift <= 0:
        fail("ERR_ZERO_UPLIFT", "requested_uplift_gallons must be greater than zero.")

    origin_contract, destination_contract = domain.directive_contracts(leg)

    row = new_row()
    row.update({
        "flight_leg_id": leg["id"],
        "requested_uplift_gallons": uplift,
        "status": "PROPOSED",
        "planned_burn_penalty_gallons": None,
        "planned_gross_savings_usd": None,
        "planned_penalty_cost_usd": None,
        "planned_net_savings_usd": None,
        "pinned_origin_price_usd_per_gal": None,
        "pinned_destination_price_usd_per_gal": None,
        "pinned_origin_contract_ref": None,
        "reconciled_burn_penalty_gallons": None,
        "reconciled_net_savings_usd": None,
        "savings_variance_usd": None,
        "revision_count": 0,
        "proposed_by_user_id": g.user_id,
        "approved_by_user_id": None,
    })
    domain.apply_planned_basis(row, leg, origin_contract, destination_contract)
    db.directives[row["id"]] = row

    for prior in domain.leg_directives(leg["id"]):
        if prior["id"] == row["id"]:
            continue
        if prior["status"] in ("PROPOSED", "NEEDS_REVISION"):
            prior["status"] = "SUPERSEDED"
            touch(prior)

    touch(leg)
    return created(ser.directive(row))


@bp.get("/fuel/flight-legs/<leg_id>/tankering-directives")
@endpoint(RISK_POLICY_ADMIN, FUEL_ANALYST, FUEL_OPS_CONTROLLER, STATION_COORDINATOR)
def list_leg_directives(leg_id):
    limit, offset = v.pagination()
    status = v.enum_filter("status", DIRECTIVE_STATUSES)

    leg = fetch.flight_leg(leg_id)
    rows = domain.leg_directives(leg["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.paginate(rows, limit, offset)
    return ok_list([ser.directive(r) for r in page], limit, offset, total)
