"""CharterContract, FlightLeg, ManifestEntry routes."""
from datetime import timedelta

from flask import Blueprint, g

import calc
import util
from util import (
    ApiError,
    apply_filters,
    body,
    check_version,
    finalize_trip,
    invalid,
    paginate,
    reconcile_trip_posture,
    req_dt,
    req_enum,
    req_int,
    req_str,
    req_version,
    opt_str,
    require_role,
    resolve_contract,
    resolve_entry,
    resolve_leg,
    resolve_member,
    resolve_team,
    resolve_trip,
)
from envelope import ok, ok_list
from state import STORE, bump, clock_now, fmt_ts, new_resource, public

bp = Blueprint("charter", __name__)


def trip_not_terminal(trip):
    if trip["posture"] in ("CLOSED", "CANCELLED"):
        raise ApiError("ERR_TRIP_ALREADY_TERMINAL", 409, "Trip already CLOSED or CANCELLED")


def trip_must_be_draft(trip):
    trip_not_terminal(trip)
    if trip["posture"] != "DRAFT":
        raise ApiError("ERR_TRIP_NOT_DRAFT", 409, "Operation requires trip posture DRAFT")


def valid_penalty_bands(bands):
    if not isinstance(bands, list) or len(bands) == 0:
        return False
    days = []
    for b in bands:
        if not isinstance(b, dict):
            return False
        d, p = b.get("days_before"), b.get("penalty_pct")
        if isinstance(d, bool) or not isinstance(d, int):
            return False
        if isinstance(p, bool) or not isinstance(p, int):
            return False
        days.append(d)
    return days == sorted(days, reverse=True)


# ---------------------------------------------------------------------------
# Charter contracts
# ---------------------------------------------------------------------------
@bp.route("/travel/teams/<teamId>/trips/<tripId>/charter-contracts", methods=["POST"])
def create_contract(teamId, tripId):
    require_role("TravelManager")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    data = body()
    vendor_code = req_str(data, "vendor_code")
    base_price = req_int(data, "base_price_cents")
    fuel_cap = req_int(data, "fuel_surcharge_cap_cents")
    seat_capacity = req_int(data, "seat_capacity")
    cargo_capacity = req_int(data, "cargo_capacity_lb")
    bands = data.get("penalty_bands")
    if not isinstance(bands, list):
        raise invalid("penalty_bands must be an array")
    trip_must_be_draft(trip)
    contract = new_resource()
    contract.update(
        {
            "trip_id": trip["id"],
            "vendor_code": vendor_code,
            "base_price_cents": base_price,
            "fuel_surcharge_cap_cents": fuel_cap,
            "seat_capacity": seat_capacity,
            "cargo_capacity_lb": cargo_capacity,
            "penalty_bands": bands,
            "status": "DRAFT",
            "executed_at": None,
            "cancelled_at": None,
            "cancellation_penalty_cents": None,
            "_kind": "contract",
        }
    )
    STORE["contracts"][contract["id"]] = contract
    return ok(public(contract), 201)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/charter-contracts", methods=["GET"])
def list_contracts(teamId, tripId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    items = calc.trip_contracts(trip)
    page, total, limit, offset = paginate(items)
    return ok_list([public(c) for c in page], total, limit, offset)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/charter-contracts/<contractId>", methods=["GET"])
def get_contract(teamId, tripId, contractId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    contract = resolve_contract(trip, contractId)
    return ok(public(contract), 200)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/charter-contracts/<contractId>/submit", methods=["POST"])
def submit_contract(teamId, tripId, contractId):
    require_role("TravelManager")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    contract = resolve_contract(trip, contractId)
    body()
    trip_not_terminal(trip)
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract must be DRAFT to submit")
    calc.recalc_party_size(trip)
    if contract["seat_capacity"] < trip["party_size"]:
        raise ApiError("ERR_INVALID_STATE", 409, "seat_capacity does not cover trip party_size")
    if not valid_penalty_bands(contract["penalty_bands"]):
        raise invalid("penalty_bands must be non-empty and sorted by days_before DESC")
    contract["status"] = "SUBMITTED"
    bump(contract)
    return ok(public(contract), 200)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/charter-contracts/<contractId>/countersign", methods=["POST"])
def countersign_contract(teamId, tripId, contractId):
    require_role("VendorRep")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    contract = resolve_contract(trip, contractId)
    body()
    trip_not_terminal(trip)
    if contract["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract must be SUBMITTED to countersign")
    contract["status"] = "VENDOR_COUNTERSIGNED"
    bump(contract)
    return ok(public(contract), 200)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/charter-contracts/<contractId>/execute", methods=["POST"])
def execute_contract(teamId, tripId, contractId):
    require_role("TravelFinanceLead")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    contract = resolve_contract(trip, contractId)
    data = body()
    expected = req_version(data, "expected_contract_version")
    check_version(contract, expected)
    trip_must_be_draft(trip)
    if contract["status"] != "VENDOR_COUNTERSIGNED":
        raise ApiError(
            "ERR_CONTRACT_NOT_VENDOR_COUNTERSIGNED",
            409,
            "Contract must be VENDOR_COUNTERSIGNED to execute",
        )
    # Charter execution window: at least 30 days before game tipoff.
    if clock_now() > trip["_tipoff"] - timedelta(days=30):
        raise ApiError(
            "ERR_CONTRACT_EXECUTION_WINDOW",
            409,
            "Fewer than 30 days remain before game_tipoff_utc",
        )
    season = STORE["seasons"][trip["season_id"]]
    exposure = contract["base_price_cents"] + contract["fuel_surcharge_cap_cents"]
    if calc.season_remaining(season) < exposure:
        raise ApiError("ERR_BUDGET_EXCEEDED", 402, "Season budget cannot cover contract exposure")
    contract["status"] = "TEAM_EXECUTED"
    contract["executed_at"] = fmt_ts(clock_now())
    bump(contract)
    calc.log_financial_event(trip, fmt_ts(clock_now()), exposure)
    finalize_trip(trip, enumerated=True)
    return ok(public(contract), 200)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/charter-contracts/<contractId>/cancel", methods=["POST"])
def cancel_contract(teamId, tripId, contractId):
    require_role("TravelManager")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    contract = resolve_contract(trip, contractId)
    body()
    trip_not_terminal(trip)
    if contract["status"] not in ("DRAFT", "SUBMITTED", "VENDOR_COUNTERSIGNED", "TEAM_EXECUTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Contract cannot be cancelled from current state")
    for leg in calc.trip_legs(trip):
        if leg.get("contract_id") == contract["id"] and leg["status"] == "DEPARTED":
            raise ApiError("ERR_INVALID_STATE", 409, "A flight leg on this contract has DEPARTED")
    penalty = calc.cancellation_penalty(contract, trip, clock_now())
    contract["status"] = "CANCELLED"
    contract["cancelled_at"] = fmt_ts(clock_now())
    contract["cancellation_penalty_cents"] = penalty
    bump(contract)
    amount = penalty if contract.get("executed_at") is None else (
        penalty - contract["base_price_cents"] - contract["fuel_surcharge_cap_cents"]
    )
    calc.log_financial_event(trip, fmt_ts(clock_now()), amount)
    # Cancel bound legs; bump their manifests.
    for leg in calc.trip_legs(trip):
        if leg.get("contract_id") == contract["id"] and leg["status"] in (
            "PLANNED",
            "BOOKED",
            "DELAYED",
            "REBOOKING",
        ):
            leg["status"] = "CANCELLED"
            bump(leg)
            for entry in calc.leg_entries(leg):
                if entry["status"] in ("PENDING", "CONFIRMED"):
                    entry["status"] = "BUMPED"
                    entry["bump_reason"] = "OVERBOOK"
                    bump(entry)
    finalize_trip(trip)
    return ok(public(contract), 200)


# ---------------------------------------------------------------------------
# Flight legs
# ---------------------------------------------------------------------------
@bp.route("/travel/teams/<teamId>/trips/<tripId>/flight-legs", methods=["POST"])
def create_leg(teamId, tripId):
    require_role("TravelCoordinator")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    data = body()
    leg_seq = req_int(data, "leg_seq")
    origin = req_str(data, "origin_code")
    dest = req_str(data, "destination_code")
    dep_raw, dep = req_dt(data, "scheduled_depart_utc")
    arr_raw, arr = req_dt(data, "scheduled_arrive_utc")
    is_charter = data.get("is_charter")
    if not isinstance(is_charter, bool):
        raise invalid("is_charter must be a boolean")
    contract_id = opt_str(data, "contract_id", None)
    trip_must_be_draft(trip)
    contract = None
    if contract_id is not None:
        contract = STORE["contracts"].get(contract_id)
        if contract is None or contract["trip_id"] != trip["id"]:
            raise ApiError("ERR_CONTRACT_NOT_FOUND", 404, "contractId does not exist within trip")
    # contract_id is required exactly when is_charter is true.
    if is_charter and contract_id is None:
        raise invalid("contract_id is required when is_charter is true")
    leg = new_resource()
    leg.update(
        {
            "trip_id": trip["id"],
            "leg_seq": leg_seq,
            "origin_code": origin,
            "destination_code": dest,
            "scheduled_depart_utc": dep_raw,
            "scheduled_arrive_utc": arr_raw,
            "is_charter": is_charter,
            "contract_id": contract_id,
            "status": "PLANNED",
            "actual_depart_utc": None,
            "actual_arrive_utc": None,
            "delay_minutes": 0,
            "rebook_generation": 0,
            "_kind": "leg",
            "_sched_depart": dep,
            "_sched_arrive": arr,
            "_reported_delay_minutes": 0,
        }
    )
    STORE["legs"][leg["id"]] = leg
    finalize_trip(trip, enumerated=True)
    return ok(public(leg), 201)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/flight-legs/<legId>", methods=["GET"])
def get_leg(teamId, tripId, legId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    leg = resolve_leg(trip, legId)
    return ok(public(leg), 200)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/flight-legs", methods=["GET"])
def list_legs(teamId, tripId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    items = calc.trip_legs(trip)
    items = apply_filters(items, ["status", "contract_id"])
    page, total, limit, offset = paginate(items)
    return ok_list([public(l) for l in page], total, limit, offset)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/charter-contracts/<contractId>/flight-legs", methods=["GET"])
def list_legs_by_contract(teamId, tripId, contractId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    contract = resolve_contract(trip, contractId)
    items = calc.children("legs", contract_id=contract["id"])
    page, total, limit, offset = paginate(items)
    return ok_list([public(l) for l in page], total, limit, offset)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/flight-legs/<legId>/book", methods=["POST"])
def book_leg(teamId, tripId, legId):
    require_role("TravelCoordinator")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    leg = resolve_leg(trip, legId)
    body()
    trip_not_terminal(trip)
    if leg["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Leg must be PLANNED to book")
    contract = None
    if leg["is_charter"]:
        if not leg.get("contract_id"):
            raise ApiError("ERR_LEG_NOT_CHARTER", 409, "Charter leg must reference a contract")
        contract = STORE["contracts"].get(leg["contract_id"])
        if contract is None:
            raise ApiError("ERR_CONTRACT_NOT_FOUND", 404, "contractId does not exist within trip")
    else:
        if leg.get("contract_id"):
            raise ApiError("ERR_LEG_NOT_CHARTER", 409, "Referenced leg is not on a charter contract")
    # Rest floor (priority 7)
    if not calc.rest_floor_ok(team, trip, leg, leg["_sched_depart"]):
        raise ApiError("ERR_REST_FLOOR_VIOLATION", 409, "Departure too soon after prior leg arrival")
    # Manifest capacity at book (charter legs): IN members must fit seats.
    if contract is not None:
        calc.recalc_party_size(trip)
        if trip["party_size"] > contract["seat_capacity"]:
            raise ApiError("ERR_MANIFEST_FULL", 409, "IN member count exceeds charter seat_capacity")
        # Referenced-target state (priority 15)
        if contract["status"] not in ("TEAM_EXECUTED", "ACTIVE"):
            raise ApiError(
                "ERR_CONTRACT_NOT_EXECUTABLE",
                409,
                "Contract must be TEAM_EXECUTED or ACTIVE to bind legs",
            )
    leg["status"] = "BOOKED"
    bump(leg)
    if contract is not None and contract["status"] == "TEAM_EXECUTED":
        contract["status"] = "ACTIVE"
        bump(contract)
    finalize_trip(trip, enumerated=True)
    return ok(public(leg), 200)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/flight-legs/<legId>/delay", methods=["POST"])
def delay_leg(teamId, tripId, legId):
    require_role("TravelCoordinator")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    leg = resolve_leg(trip, legId)
    data = body()
    delay_minutes = req_int(data, "delay_minutes")
    trip_not_terminal(trip)
    if leg["status"] != "BOOKED":
        raise ApiError("ERR_LEG_NOT_BOOKED", 409, "Operation requires leg in BOOKED")
    if delay_minutes <= 0:
        raise invalid("delay_minutes must be positive")
    leg["status"] = "DELAYED"
    leg["_reported_delay_minutes"] = leg.get("_reported_delay_minutes", 0) + delay_minutes
    leg["_sched_arrive"] = leg["_sched_arrive"] + timedelta(minutes=delay_minutes)
    leg["scheduled_arrive_utc"] = fmt_ts(leg["_sched_arrive"])
    bump(leg)
    # Downstream legs whose departure violates the rest floor -> REBOOKING.
    new_arrive = leg["_sched_arrive"]
    req = calc.rest_required_minutes(team["league_rest_policy"], leg)
    for other in calc.trip_legs(trip):
        if other["leg_seq"] > leg["leg_seq"] and other["status"] == "BOOKED":
            if other["_sched_depart"] < new_arrive + timedelta(minutes=req):
                other["status"] = "REBOOKING"
                bump(other)
    # Shipments riding this leg's contract move IN_TRANSIT -> DELAYED.
    if leg.get("contract_id"):
        for s in calc.children("shipments", assigned_contract_id=leg["contract_id"]):
            if s["status"] == "IN_TRANSIT":
                s["status"] = "DELAYED"
                bump(s)
    finalize_trip(trip, enumerated=True)
    return ok(public(leg), 200)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/flight-legs/<legId>/rebook", methods=["POST"])
def rebook_leg(teamId, tripId, legId):
    require_role("TravelCoordinator")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    leg = resolve_leg(trip, legId)
    data = body()
    dep_raw, dep = req_dt(data, "scheduled_depart_utc")
    arr_raw, arr = req_dt(data, "scheduled_arrive_utc")
    trip_not_terminal(trip)
    from_status = leg["status"]
    if from_status not in ("DELAYED", "REBOOKING"):
        raise ApiError("ERR_INVALID_STATE", 409, "Leg must be DELAYED or REBOOKING to rebook")
    if not calc.rest_floor_ok(team, trip, leg, dep):
        raise ApiError("ERR_REST_FLOOR_VIOLATION", 409, "Departure too soon after prior leg arrival")
    if from_status == "DELAYED" and leg["is_charter"] and leg.get("contract_id"):
        contract = STORE["contracts"].get(leg["contract_id"])
        if contract is not None:
            calc.recalc_party_size(trip)
            if trip["party_size"] > contract["seat_capacity"]:
                raise ApiError("ERR_MANIFEST_FULL", 409, "IN member count exceeds charter seat_capacity")
    leg["status"] = "BOOKED"
    leg["scheduled_depart_utc"] = dep_raw
    leg["scheduled_arrive_utc"] = arr_raw
    leg["_sched_depart"] = dep
    leg["_sched_arrive"] = arr
    leg["_reported_delay_minutes"] = 0
    leg["rebook_generation"] += 1
    bump(leg)
    for entry in calc.leg_entries(leg):
        if entry["is_ticketed"]:
            entry["is_ticketed"] = False
            bump(entry)
    season = STORE["seasons"][trip["season_id"]]
    finalize_trip(trip, enumerated=(from_status == "DELAYED"))
    reconcile_trip_posture(trip, season)
    return ok(public(leg), 200)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/flight-legs/<legId>/depart", methods=["POST"])
def depart_leg(teamId, tripId, legId):
    require_role("TravelCoordinator")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    leg = resolve_leg(trip, legId)
    body()
    trip_not_terminal(trip)
    if leg["status"] != "BOOKED":
        raise ApiError("ERR_LEG_NOT_BOOKED", 409, "Operation requires leg in BOOKED")
    if any(e["status"] == "PENDING" for e in calc.leg_entries(leg)):
        raise ApiError("ERR_INVALID_STATE", 409, "All PENDING manifest entries must be resolved")
    leg["status"] = "DEPARTED"
    leg["actual_depart_utc"] = fmt_ts(clock_now())
    bump(leg)
    # First leg of trip: LOCKED -> IN_FLIGHT.
    active_legs = [l for l in calc.trip_legs(trip) if l["status"] != "CANCELLED"]
    if active_legs and leg["leg_seq"] == min(l["leg_seq"] for l in active_legs):
        if trip["posture"] == "LOCKED":
            trip["posture"] = "IN_FLIGHT"
            bump(trip)
            g._bumped_trips = getattr(g, "_bumped_trips", set()) | {trip["id"]}
    # Shipments loaded on this leg's contract move to IN_TRANSIT.
    if leg.get("contract_id"):
        for s in calc.children("shipments", assigned_contract_id=leg["contract_id"]):
            if s["status"] in ("LOADED", "DELAYED"):
                s["status"] = "IN_TRANSIT"
                bump(s)
    finalize_trip(trip)
    return ok(public(leg), 200)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/flight-legs/<legId>/arrive", methods=["POST"])
def arrive_leg(teamId, tripId, legId):
    require_role("TravelCoordinator")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    leg = resolve_leg(trip, legId)
    body()
    trip_not_terminal(trip)
    if leg["status"] != "DEPARTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Operation requires leg in DEPARTED")
    leg["status"] = "ARRIVED"
    leg["actual_arrive_utc"] = fmt_ts(clock_now())
    delta = clock_now() - leg["_sched_arrive"]
    leg["delay_minutes"] = int(delta.total_seconds() // 60)
    bump(leg)
    for entry in calc.leg_entries(leg):
        if entry["status"] == "CONFIRMED":
            entry["status"] = "FLOWN"
            bump(entry)
    # Last leg arrived: IN_FLIGHT -> RECOVERING.
    remaining = [
        l
        for l in calc.trip_legs(trip)
        if l["status"] not in ("ARRIVED", "CANCELLED")
    ]
    if not remaining and trip["posture"] == "IN_FLIGHT":
        trip["posture"] = "RECOVERING"
        bump(trip)
        g._bumped_trips = getattr(g, "_bumped_trips", set()) | {trip["id"]}
    finalize_trip(trip)
    return ok(public(leg), 200)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/flight-legs/<legId>/cancel", methods=["POST"])
def cancel_leg(teamId, tripId, legId):
    require_role("TravelCoordinator")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    leg = resolve_leg(trip, legId)
    body()
    trip_not_terminal(trip)
    if leg["status"] not in ("PLANNED", "BOOKED", "DELAYED", "REBOOKING"):
        raise ApiError("ERR_INVALID_STATE", 409, "Leg cannot be cancelled from current state")
    leg["status"] = "CANCELLED"
    bump(leg)
    for entry in calc.leg_entries(leg):
        if entry["status"] in ("PENDING", "CONFIRMED"):
            entry["status"] = "BUMPED"
            entry["bump_reason"] = "OVERBOOK"
            bump(entry)
    finalize_trip(trip)
    return ok(public(leg), 200)


# ---------------------------------------------------------------------------
# Manifest entries
# ---------------------------------------------------------------------------
@bp.route("/travel/teams/<teamId>/trips/<tripId>/flight-legs/<legId>/manifest", methods=["POST"])
def create_entry(teamId, tripId, legId):
    require_role("TravelCoordinator")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    leg = resolve_leg(trip, legId)
    data = body()
    member_id = req_str(data, "member_id")
    seat = opt_str(data, "seat_assignment", None)
    trip_not_terminal(trip)
    member = resolve_member(trip, member_id)
    entry = new_resource()
    entry.update(
        {
            "flight_leg_id": leg["id"],
            "member_id": member["id"],
            "seat_assignment": seat,
            "is_ticketed": False,
            "status": "PENDING",
            "bump_reason": None,
            "_kind": "entry",
        }
    )
    STORE["entries"][entry["id"]] = entry
    return ok(public(entry), 201)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/flight-legs/<legId>/manifest", methods=["GET"])
def list_entries(teamId, tripId, legId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    leg = resolve_leg(trip, legId)
    items = calc.leg_entries(leg)
    if g.user_role == "TeamMember":
        items = [e for e in items if e["member_id"] == g.user_id]
    items = apply_filters(items, ["member_id"])
    page, total, limit, offset = paginate(items)
    return ok_list([public(e) for e in page], total, limit, offset)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/members/<memberId>/manifest", methods=["GET"])
def list_entries_by_member(teamId, tripId, memberId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    member = resolve_member(trip, memberId)
    if g.user_role == "TeamMember":
        util.check_team_member_owns(member["id"])
    leg_ids = {l["id"] for l in calc.trip_legs(trip)}
    items = [
        e
        for e in STORE["entries"].values()
        if e["member_id"] == member["id"] and e["flight_leg_id"] in leg_ids
    ]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total, limit, offset = paginate(items)
    return ok_list([public(e) for e in page], total, limit, offset)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/flight-legs/<legId>/manifest/<entryId>", methods=["GET"])
def get_entry(teamId, tripId, legId, entryId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    leg = resolve_leg(trip, legId)
    entry = resolve_entry(leg, entryId)
    util.team_member_read_guard(entry)
    return ok(public(entry), 200)


def venue_requires_credential(trip, venue_code):
    return any(
        c["trip_id"] == trip["id"] and c["venue_code"] == venue_code
        for c in STORE["credentials"].values()
    )


def member_has_approved_credential(trip, member_id, venue_code):
    return any(
        c["trip_id"] == trip["id"]
        and c["member_id"] == member_id
        and c["venue_code"] == venue_code
        and c["status"] == "APPROVED"
        for c in STORE["credentials"].values()
    )


@bp.route(
    "/travel/teams/<teamId>/trips/<tripId>/flight-legs/<legId>/manifest/<entryId>/confirm",
    methods=["POST"],
)
def confirm_entry(teamId, tripId, legId, entryId):
    require_role("TravelCoordinator")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    leg = resolve_leg(trip, legId)
    entry = resolve_entry(leg, entryId)
    body()
    trip_not_terminal(trip)
    if leg["status"] not in ("BOOKED", "DELAYED"):
        raise ApiError("ERR_LEG_NOT_BOOKED", 409, "Leg must be BOOKED or DELAYED to confirm")
    if entry["status"] != "PENDING":
        raise ApiError("ERR_ENTRY_NOT_PENDING", 409, "Manifest entry must be PENDING")
    member = STORE["members"][entry["member_id"]]
    # Credential gate (priority 8) before capacity (priority 11).
    if venue_requires_credential(trip, leg["destination_code"]):
        if not member_has_approved_credential(trip, member["id"], leg["destination_code"]):
            raise ApiError(
                "ERR_CREDENTIAL_REQUIRED",
                409,
                "Member lacks APPROVED credential for destination venue",
            )
    if leg["is_charter"] and leg.get("contract_id"):
        contract = STORE["contracts"].get(leg["contract_id"])
        if contract is not None:
            confirmed = len([e for e in calc.leg_entries(leg) if e["status"] == "CONFIRMED"])
            if confirmed >= contract["seat_capacity"]:
                raise ApiError("ERR_MANIFEST_FULL", 409, "Confirmed manifest count equals charter seat_capacity")
    # Referenced-target state (priority 15): member must be IN.
    if member["status"] != "IN":
        raise ApiError("ERR_MEMBER_NOT_IN", 409, "Referenced member status is not IN")
    entry["status"] = "CONFIRMED"
    entry["is_ticketed"] = True
    bump(entry)
    return ok(public(entry), 200)


@bp.route(
    "/travel/teams/<teamId>/trips/<tripId>/flight-legs/<legId>/manifest/<entryId>/bump",
    methods=["POST"],
)
def bump_entry(teamId, tripId, legId, entryId):
    require_role("TravelCoordinator")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    leg = resolve_leg(trip, legId)
    entry = resolve_entry(leg, entryId)
    data = body()
    reason = req_enum(data, "bump_reason", calc.BUMP_REASONS)
    trip_not_terminal(trip)
    if entry["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, "Manifest entry must be CONFIRMED to bump")
    entry["status"] = "BUMPED"
    entry["bump_reason"] = reason
    bump(entry)
    return ok(public(entry), 200)
