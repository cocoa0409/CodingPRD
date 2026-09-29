"""Flight legs: creation with hard checks, permissive retiming, and the leg actions."""
from flask import Blueprint

import calc
import cascades
import derive
import reqval as rv
from db import mark, store
from errors import ApiError
from middleware import authenticate, require_ownership
from response import ok, written
from routes.common import (
    READ_ROLES,
    list_response,
    read_one,
    require_season_open,
    season_of_version,
    version_of_leg,
)
from util import date_key, dt_of, iso_week_bounds, minutes_between

bp = Blueprint("flight_legs", __name__)

PLANNER = ("NetworkPlanner",)
MAX_BLOCK_MINUTES = 1080
ROTATION_ERROR = {
    "INFEASIBLE_CONTINUITY": "ERR_ROTATION_CONTINUITY_BROKEN",
    "INFEASIBLE_TURN": "ERR_TURN_TIME_VIOLATION",
    "INFEASIBLE_BLOCK_CAP": "ERR_DAILY_BLOCK_CAP_EXCEEDED",
}


def _curfew_check(origin, dest, dep, arr, waiver):
    """Band 9. A waiver converts the rejection into a scored penalty."""
    if waiver:
        return
    if calc.in_curfew(origin, dt_of(dep)) or calc.in_curfew(dest, dt_of(arr)):
        raise ApiError("ERR_CURFEW_VIOLATION")


def _gate_check(candidate):
    """Band 10. Aggregated over every carrier and version at the station."""
    legs = [leg for leg in store.values("flight_legs") if leg["status"] != "CANCELLED"]
    legs.append(candidate)
    endpoints = [
        (candidate["origin_station_id"], date_key(dt_of(candidate["dep_utc"]))),
        (candidate["dest_station_id"], date_key(dt_of(candidate["arr_utc"]))),
    ]
    for station_id, day in endpoints:
        station = store.get("stations", station_id)
        if station is None:
            continue
        peak = calc.peak_concurrency(calc.gate_intervals(legs, station_id, day))
        if peak > station["gate_count"]:
            raise ApiError("ERR_GATE_CAPACITY_EXCEEDED")


def _authorities_for(carrier, pair, single_country):
    rows = []
    for authority in store.values("route_authorities"):
        if authority["carrier_id"] != carrier["id"]:
            continue
        countries = {authority["origin_country_code"], authority["dest_country_code"]}
        if single_country:
            if single_country in countries:
                rows.append(authority)
        elif countries == pair:
            rows.append(authority)
    return rows


def _weekly_count(carrier, pair, dep):
    week_start, week_end = iso_week_bounds(dt_of(dep))
    total = 1
    for leg in store.values("flight_legs"):
        if leg["status"] == "CANCELLED":
            continue
        version = store.get("schedule_versions", leg["schedule_version_id"])
        if version is None or version["carrier_id"] != carrier["id"]:
            continue
        origin = store.get("stations", leg["origin_station_id"])
        dest = store.get("stations", leg["dest_station_id"])
        if origin is None or dest is None:
            continue
        if {origin["country_code"], dest["country_code"]} != pair:
            continue
        moment = dt_of(leg["dep_utc"])
        if week_start <= moment < week_end:
            total += 1
    return total


def _traffic_rights_check(carrier, origin, dest, dep):
    """Band 11. Authorities are matched as an unordered country pair."""
    origin_country = origin["country_code"]
    dest_country = dest["country_code"]
    if origin_country == dest_country and origin_country == carrier["country_code"]:
        return
    cabotage = origin_country == dest_country
    pair = {origin_country, dest_country}
    candidates = _authorities_for(carrier, pair, origin_country if cabotage else None)
    if not candidates:
        raise ApiError("ERR_ROUTE_AUTHORITY_MISSING")
    moment = dt_of(dep)
    live = [
        authority for authority in candidates
        if authority["status"] == "ACTIVE"
        and dt_of(authority["granted_from_utc"]) <= moment <= dt_of(authority["granted_until_utc"])
    ]
    if not live:
        raise ApiError("ERR_ROUTE_AUTHORITY_INACTIVE")
    if cabotage:
        live = [authority for authority in live if authority["freedom_type"] == "SEVENTH"]
        if not live:
            raise ApiError("ERR_CABOTAGE_PROHIBITED")
    authority = live[0]
    if _weekly_count(carrier, pair, dep) > authority["weekly_frequency_cap"]:
        raise ApiError("ERR_FREQUENCY_CAP_EXCEEDED")


def _season_window_check(season, dep, arr):
    """Band 12."""
    departure = dt_of(dep)
    arrival = dt_of(arr)
    if departure >= arrival:
        raise ApiError("ERR_LEG_OUTSIDE_SEASON_WINDOW")
    if departure < dt_of(season["start_date"]) or arrival > dt_of(season["end_date"]):
        raise ApiError("ERR_LEG_OUTSIDE_SEASON_WINDOW")


@bp.post("/flight-legs")
def create_flight_leg():
    authenticate(PLANNER)
    payload = rv.body()
    version_id = rv.req_str(payload, "schedule_version_id", 1)
    flight_number = rv.req_str(payload, "flight_number", 3, 8)
    origin_id = rv.req_str(payload, "origin_station_id", 1)
    dest_id = rv.req_str(payload, "dest_station_id", 1)
    dep = rv.req_dt(payload, "dep_utc")
    arr = rv.req_dt(payload, "arr_utc")
    fleet_type = rv.req_str(payload, "fleet_type_code", 3, 4, r"[A-Z0-9]{3,4}")
    upstream_id = rv.opt_str(payload, "connects_from_leg_id", 1)
    marketing = rv.opt_str_list(payload, "marketing_carrier_ids", 4)
    waiver = rv.opt_str(payload, "curfew_waiver_reference", 4, 32)
    if origin_id == dest_id:
        rv.bad("dest_station_id must differ from origin_station_id.")
    if minutes_between(dt_of(dep), dt_of(arr)) > MAX_BLOCK_MINUTES:
        rv.bad("The elapsed time between dep_utc and arr_utc may not exceed 1080 minutes.")

    for carrier_id in marketing:
        store.require("carriers", carrier_id)
    origin = store.require("stations", origin_id)
    dest = store.require("stations", dest_id)
    version = store.require("schedule_versions", version_id)
    upstream = store.require("flight_legs", upstream_id) if upstream_id else None
    if version["carrier_id"] in marketing:
        rv.bad("marketing_carrier_ids may not contain the version's own carrier.")

    require_ownership(version["carrier_id"])
    season = season_of_version(version)
    require_season_open(season)
    if version["filing_status"] != "DRAFT":
        raise ApiError("ERR_SCHEDULE_VERSION_STATE_INVALID")

    _curfew_check(origin, dest, dep, arr, waiver)

    candidate = {
        "id": None,
        "schedule_version_id": version_id,
        "origin_station_id": origin_id,
        "dest_station_id": dest_id,
        "dep_utc": dep,
        "arr_utc": arr,
        "status": "DRAFT",
        "connects_from_leg_id": upstream_id,
        "block_minutes": minutes_between(dt_of(dep), dt_of(arr)),
    }
    if upstream is not None:
        if (
            upstream["schedule_version_id"] != version_id
            or upstream["dest_station_id"] != origin_id
        ):
            raise ApiError("ERR_CONNECTION_STATION_MISMATCH")
        _, shortfall = derive.connect_figures(candidate, upstream)
        if shortfall > 0:
            raise ApiError("ERR_MIN_CONNECT_TIME_VIOLATION")
    _gate_check(candidate)

    carrier = store.require("carriers", version["carrier_id"])
    _traffic_rights_check(carrier, origin, dest, dep)
    _season_window_check(season, dep, arr)

    connect_minutes, shortfall = derive.connect_figures(candidate, upstream)
    row = store.insert("flight_legs", {
        "schedule_version_id": version_id,
        "flight_number": flight_number,
        "origin_station_id": origin_id,
        "dest_station_id": dest_id,
        "dep_utc": dep,
        "arr_utc": arr,
        "fleet_type_code": fleet_type,
        "assigned_aircraft_id": None,
        "departure_slot_holding_id": None,
        "arrival_slot_holding_id": None,
        "connects_from_leg_id": upstream_id,
        "marketing_carrier_ids": marketing,
        "curfew_waiver_reference": waiver,
        "booked_first": 0,
        "booked_business": 0,
        "booked_economy": 0,
        "status": "DRAFT",
        "cancellation_reason": None,
        "block_minutes": minutes_between(dt_of(dep), dt_of(arr)),
        "is_international": origin["country_code"] != dest["country_code"],
        "mct_shortfall_minutes": shortfall,
        "connect_minutes": connect_minutes,
        "open_obligation_count": 0,
    })
    return written(row, 201)


@bp.get("/flight-legs/<flight_leg_id>")
def get_flight_leg(flight_leg_id):
    return ok(read_one("flight_legs", flight_leg_id))


@bp.get("/flight-legs")
def list_flight_legs():
    authenticate(READ_ROLES)
    return list_response("flight_legs", [
        ("schedule_version_id", rv.q_str("schedule_version_id")),
        ("origin_station_id", rv.q_str("origin_station_id")),
        ("dest_station_id", rv.q_str("dest_station_id")),
        ("assigned_aircraft_id", rv.q_str("assigned_aircraft_id")),
        ("departure_slot_holding_id", rv.q_str("departure_slot_holding_id")),
        ("arrival_slot_holding_id", rv.q_str("arrival_slot_holding_id")),
        ("connects_from_leg_id", rv.q_str("connects_from_leg_id")),
        ("status", rv.q_enum("status", "leg_status")),
        ("flight_number", rv.q_str("flight_number")),
    ])


@bp.patch("/flight-legs/<flight_leg_id>")
def retime_flight_leg(flight_leg_id):
    authenticate(PLANNER)
    leg = store.require("flight_legs", flight_leg_id)
    payload = rv.body()
    new_dep = rv.opt_dt(payload, "dep_utc", leg["dep_utc"])
    new_arr = rv.opt_dt(payload, "arr_utc", leg["arr_utc"])
    new_number = rv.opt_str(payload, "flight_number", 3, 8, default=leg["flight_number"])
    waiver_supplied = rv.present(payload, "curfew_waiver_reference")
    new_waiver = rv.opt_str(
        payload, "curfew_waiver_reference", 4, 32, default=leg["curfew_waiver_reference"]
    )
    if minutes_between(dt_of(new_dep), dt_of(new_arr)) > MAX_BLOCK_MINUTES:
        rv.bad("The elapsed time between dep_utc and arr_utc may not exceed 1080 minutes.")

    version = version_of_leg(leg)
    require_ownership(version["carrier_id"])
    if leg["status"] == "CANCELLED":
        raise ApiError("ERR_FLIGHT_LEG_STATE_INVALID")

    origin = store.get("stations", leg["origin_station_id"])
    dest = store.get("stations", leg["dest_station_id"])
    _curfew_check(origin, dest, new_dep, new_arr, new_waiver)
    _season_window_check(season_of_version(version), new_dep, new_arr)

    previous_dep = leg["dep_utc"]
    previous_arr = leg["arr_utc"]
    retimed = new_dep != previous_dep or new_arr != previous_arr

    leg["flight_number"] = new_number
    if waiver_supplied:
        leg["curfew_waiver_reference"] = new_waiver
    mark(leg)

    if retimed:
        leg["dep_utc"] = new_dep
        leg["arr_utc"] = new_arr
        leg["block_minutes"] = minutes_between(dt_of(new_dep), dt_of(new_arr))
        cascades.detach_leg_slots(leg)
        if leg["status"] == "FILED":
            leg["status"] = "REFILE_REQUIRED"
        elif leg["status"] == "SLOT_BACKED":
            leg["status"] = "ASSIGNED"
            if derive.is_fully_slotted(leg):
                leg["status"] = "SLOT_BACKED"
        magnitude = max(
            abs(minutes_between(dt_of(previous_dep), dt_of(new_dep))),
            abs(minutes_between(dt_of(previous_arr), dt_of(new_arr))),
        )
        cascades.raise_obligation(leg, "RETIME", magnitude, previous_dep, previous_arr)
        cascades.waive_if_reverted(leg)

    return written(leg)


@bp.post("/flight-legs/<flight_leg_id>/assign-aircraft")
def assign_aircraft(flight_leg_id):
    authenticate(PLANNER)
    leg = store.require("flight_legs", flight_leg_id)
    payload = rv.body()
    aircraft_id = rv.req_str(payload, "aircraft_id", 1)
    aircraft = store.require("aircraft", aircraft_id)
    version = version_of_leg(leg)
    require_ownership(version["carrier_id"])
    if leg["status"] != "DRAFT":
        raise ApiError("ERR_FLIGHT_LEG_STATE_INVALID")
    if aircraft["status"] != "IN_SERVICE":
        raise ApiError("ERR_AIRCRAFT_NOT_IN_SERVICE")
    if aircraft["fleet_type_code"] != leg["fleet_type_code"]:
        raise ApiError("ERR_FLEET_TYPE_MISMATCH")
    if aircraft["carrier_id"] != version["carrier_id"]:
        raise ApiError("ERR_AIRCRAFT_CARRIER_MISMATCH")

    leg["assigned_aircraft_id"] = aircraft_id
    verdict, _, _, _ = calc.rotation_walk(
        aircraft, derive.legs_of_aircraft(aircraft_id), derive.station
    )
    if verdict in ROTATION_ERROR:
        leg["assigned_aircraft_id"] = None
        raise ApiError(ROTATION_ERROR[verdict])

    leg["status"] = "ASSIGNED"
    if derive.is_fully_slotted(leg):
        leg["status"] = "SLOT_BACKED"
    mark(leg)
    return written(leg)


@bp.post("/flight-legs/<flight_leg_id>/attach-slot")
def attach_slot(flight_leg_id):
    authenticate(PLANNER)
    leg = store.require("flight_legs", flight_leg_id)
    payload = rv.body()
    holding_id = rv.req_str(payload, "slot_holding_id", 1)
    movement = rv.req_enum(payload, "movement_type", "movement_type")
    holding = store.require("slot_holdings", holding_id)
    version = version_of_leg(leg)
    require_ownership(version["carrier_id"])

    if leg["status"] not in ("DRAFT", "ASSIGNED", "REFILE_REQUIRED"):
        raise ApiError("ERR_FLIGHT_LEG_STATE_INVALID")
    if holding["holding_status"] != "HELD":
        raise ApiError("ERR_SLOT_HOLDING_STATE_INVALID")
    if holding["pending_transaction_id"] is not None:
        raise ApiError("ERR_SLOT_ENCUMBERED")

    if movement == "DEPARTURE":
        expected_station = leg["origin_station_id"]
        moment = dt_of(leg["dep_utc"])
        field = "departure_slot_holding_id"
    else:
        expected_station = leg["dest_station_id"]
        moment = dt_of(leg["arr_utc"])
        field = "arrival_slot_holding_id"
    if holding["station_id"] != expected_station:
        raise ApiError("ERR_SLOT_STATION_MISMATCH")
    if holding["carrier_id"] != version["carrier_id"]:
        raise ApiError("ERR_SLOT_CARRIER_MISMATCH")
    slot_moment = dt_of(holding["slot_time_utc"])
    same_time = (
        slot_moment.hour == moment.hour
        and slot_moment.minute == moment.minute
        and slot_moment.second == moment.second
        and slot_moment.microsecond == moment.microsecond
    )
    if not same_time or str(moment.isoweekday()) not in holding["days_of_week"]:
        raise ApiError("ERR_SLOT_TIME_MISMATCH")
    if holding["attached_operations"] >= holding["planned_operations"]:
        raise ApiError("ERR_SLOT_SERIES_OVERSUBSCRIBED")

    leg[field] = holding_id
    mark(leg)
    mark(holding)
    if leg["assigned_aircraft_id"] and derive.is_fully_slotted(leg):
        if leg["status"] in ("ASSIGNED", "REFILE_REQUIRED"):
            leg["status"] = "SLOT_BACKED"
            cascades.waive_if_reverted(leg)
    return written(leg)


@bp.post("/flight-legs/<flight_leg_id>/cancel")
def cancel_flight_leg(flight_leg_id):
    authenticate(PLANNER)
    leg = store.require("flight_legs", flight_leg_id)
    payload = rv.body()
    reason = rv.req_str(payload, "reason", 1, 500)
    version = version_of_leg(leg)
    require_ownership(version["carrier_id"])
    if leg["status"] == "CANCELLED":
        raise ApiError("ERR_FLIGHT_LEG_STATE_INVALID")
    cascades.cancel_leg(leg, reason)
    return written(leg)


@bp.post("/flight-legs/<flight_leg_id>/booking-snapshot")
def booking_snapshot(flight_leg_id):
    authenticate(("NetworkPlanner", "ComplianceOfficer"))
    leg = store.require("flight_legs", flight_leg_id)
    payload = rv.body()
    first = rv.req_int(payload, "booked_first", 0)
    business = rv.req_int(payload, "booked_business", 0)
    economy = rv.req_int(payload, "booked_economy", 0)
    version = version_of_leg(leg)
    require_ownership(version["carrier_id"])
    if leg["status"] == "CANCELLED":
        raise ApiError("ERR_FLIGHT_LEG_STATE_INVALID")
    leg["booked_first"] = first
    leg["booked_business"] = business
    leg["booked_economy"] = economy
    mark(leg)
    return written(leg)
