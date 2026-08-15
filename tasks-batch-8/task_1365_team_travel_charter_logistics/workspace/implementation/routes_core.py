"""Clock, Team, Season, Trip, TravelPartyMember routes."""
from datetime import timedelta

from flask import Blueprint, g, request

import calc
import util
from util import (
    ApiError,
    apply_filters,
    body,
    check_version,
    finalize_trip,
    invalid,
    not_found,
    paginate,
    req_date,
    req_dt,
    req_enum,
    req_int,
    req_str,
    req_version,
    opt_int,
    opt_bool,
    opt_str,
    require_role,
    resolve_season,
    resolve_team,
    resolve_trip,
    resolve_member,
    team_member_read_guard,
)
from envelope import ok, ok_list
from state import STORE, bump, clock_now, clock_set, fmt_ts, new_resource, public, parse_dt

bp = Blueprint("core", __name__)


def serialize_season(s):
    out = public(s)
    committed, projected = calc.season_counters(s)
    out["committed_cost_cents"] = committed
    out["projected_cost_cents"] = projected
    return out


def trip_not_terminal(trip):
    if trip["posture"] in ("CLOSED", "CANCELLED"):
        raise ApiError("ERR_TRIP_ALREADY_TERMINAL", 409, "Trip already CLOSED or CANCELLED")


def trip_must_be_draft(trip):
    trip_not_terminal(trip)
    if trip["posture"] != "DRAFT":
        raise ApiError("ERR_TRIP_NOT_DRAFT", 409, "Operation requires trip posture DRAFT")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.route("/travel/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role("TravelOpsAdmin")
    data = body()
    raw = req_str(data, "to_iso8601")
    dt = parse_dt(raw)
    if dt is None:
        raise invalid("Invalid datetime: to_iso8601")
    clock_set(dt)
    util.sweep_clock()
    return ok({"now_utc": fmt_ts(dt)}, 200)


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------
@bp.route("/travel/teams", methods=["POST"])
def create_team():
    require_role("TravelOpsAdmin")
    data = body()
    team_code = req_str(data, "team_code")
    display_name = req_str(data, "display_name")
    policy = req_enum(data, "league_rest_policy", calc.REST_POLICIES) if "league_rest_policy" in data else "STANDARD"
    for t in STORE["teams"].values():
        if t["team_code"] == team_code:
            raise invalid("team_code must be unique across all teams")
    team = new_resource()
    team.update(
        {
            "team_code": team_code,
            "display_name": display_name,
            "league_rest_policy": policy,
            "active_season_id": None,
            "_kind": "team",
        }
    )
    STORE["teams"][team["id"]] = team
    return ok(public(team), 201)


@bp.route("/travel/teams/<teamId>", methods=["GET"])
def get_team(teamId):
    team = resolve_team(teamId)
    return ok(public(team), 200)


@bp.route("/travel/teams", methods=["GET"])
def list_teams():
    items = sorted(STORE["teams"].values(), key=lambda r: (r["created_at"], r["_seq"]))
    items = apply_filters(items, ["active_season_id"])
    page, total, limit, offset = paginate(items)
    return ok_list([public(t) for t in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Seasons
# ---------------------------------------------------------------------------
@bp.route("/travel/teams/<teamId>/seasons", methods=["POST"])
def create_season(teamId):
    require_role("TravelFinanceLead")
    team = resolve_team(teamId)
    data = body()
    label = req_str(data, "label")
    budget = req_int(data, "travel_budget_cents")
    season = new_resource()
    season.update(
        {
            "team_id": team["id"],
            "label": label,
            "travel_budget_cents": budget,
            "committed_cost_cents": 0,
            "projected_cost_cents": 0,
            "status": "OPEN",
            "_kind": "season",
        }
    )
    STORE["seasons"][season["id"]] = season
    team["active_season_id"] = season["id"]
    bump(team)
    return ok(serialize_season(season), 201)


@bp.route("/travel/teams/<teamId>/seasons", methods=["GET"])
def list_seasons(teamId):
    team = resolve_team(teamId)
    items = calc.children("seasons", team_id=team["id"])
    page, total, limit, offset = paginate(items)
    return ok_list([serialize_season(s) for s in page], total, limit, offset)


@bp.route("/travel/teams/<teamId>/seasons/<seasonId>", methods=["GET"])
def get_season(teamId, seasonId):
    team = resolve_team(teamId)
    season = resolve_season(team, seasonId)
    return ok(serialize_season(season), 200)


@bp.route("/travel/teams/<teamId>/seasons/<seasonId>/close", methods=["POST"])
def close_season(teamId, seasonId):
    require_role("TravelFinanceLead")
    team = resolve_team(teamId)
    season = resolve_season(team, seasonId)
    if season["status"] == "CLOSED":
        raise ApiError("ERR_SEASON_CLOSED", 409, "Season is already CLOSED")
    trips = calc.children("trips", season_id=season["id"])
    if any(t["posture"] not in ("CLOSED", "CANCELLED") for t in trips):
        raise ApiError("ERR_INVALID_STATE", 409, "All trips in season must be CLOSED or CANCELLED")
    committed, projected = calc.season_counters(season)
    if projected != committed:
        raise ApiError("ERR_INVALID_STATE", 409, "Open estimates remain in season")
    season["status"] = "CLOSED"
    bump(season)
    if team.get("active_season_id") == season["id"]:
        team["active_season_id"] = None
        bump(team)
    return ok(serialize_season(season), 200)


# ---------------------------------------------------------------------------
# Trips
# ---------------------------------------------------------------------------
@bp.route("/travel/teams/<teamId>/trips", methods=["POST"])
def create_trip(teamId):
    require_role("TravelManager")
    team = resolve_team(teamId)
    data = body()
    season_id = req_str(data, "season_id")
    destination_code = req_str(data, "destination_code")
    tipoff_raw, tipoff = req_dt(data, "game_tipoff_utc")
    ret_raw, ret = req_dt(data, "return_arrival_utc")
    season = resolve_season(team, season_id)
    if season["status"] != "OPEN":
        raise ApiError("ERR_SEASON_CLOSED", 409, "Season is CLOSED; no new child state permitted")
    trip = new_resource()
    trip.update(
        {
            "team_id": team["id"],
            "season_id": season["id"],
            "destination_code": destination_code,
            "game_tipoff_utc": tipoff_raw,
            "return_arrival_utc": ret_raw,
            "party_size": 0,
            "estimated_cost_cents": 0,
            "actual_cost_cents": 0,
            "posture": "DRAFT",
            "disruption_seq": 0,
            "_kind": "trip",
            "_tipoff": tipoff,
            "_return": ret,
            "_event_log": [],
            "_incurred_loss_cents": 0,
        }
    )
    STORE["trips"][trip["id"]] = trip
    return ok(public(trip), 201)


@bp.route("/travel/teams/<teamId>/trips", methods=["GET"])
def list_trips(teamId):
    team = resolve_team(teamId)
    items = calc.children("trips", team_id=team["id"])
    items = apply_filters(items, ["season_id"])
    page, total, limit, offset = paginate(items)
    return ok_list([public(t) for t in page], total, limit, offset)


@bp.route("/travel/teams/<teamId>/trips/<tripId>", methods=["GET"])
def get_trip(teamId, tripId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    return ok(public(trip), 200)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/lock", methods=["POST"])
def lock_trip(teamId, tripId):
    require_role("TravelManager")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    data = body()
    expected = req_version(data, "expected_trip_version")
    check_version(trip, expected)
    trip_must_be_draft(trip)
    calc.recalc_party_size(trip)
    if trip["party_size"] < 1:
        raise ApiError("ERR_INVALID_STATE", 409, "Trip requires at least one IN party member")
    legs = calc.trip_legs(trip)
    if not any(l["leg_seq"] == 1 and l["status"] == "BOOKED" for l in legs):
        raise ApiError("ERR_LEG_NOT_BOOKED", 409, "Outbound leg (leg_seq=1) must be BOOKED")
    blocks = calc.trip_blocks(trip)
    if not any(b["posture"] in ("HOLDING", "NAME_LIST_DUE", "LOCKED") for b in blocks):
        raise ApiError("ERR_INVALID_STATE", 409, "Trip requires a hotel block in HOLDING, NAME_LIST_DUE or LOCKED")
    season = STORE["seasons"][trip["season_id"]]
    estimate = calc.compute_estimate(trip)
    if calc.season_remaining(season) < estimate:
        raise ApiError("ERR_BUDGET_EXCEEDED", 402, "Trip estimate exceeds season remaining budget")
    trip["estimated_cost_cents"] = estimate
    trip["posture"] = "LOCKED"
    bump(trip)
    g._bumped_trips = getattr(g, "_bumped_trips", set()) | {trip["id"]}
    bump(season)
    return ok(public(trip), 200)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/close", methods=["POST"])
def close_trip(teamId, tripId):
    require_role("TravelFinanceLead")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    body()
    trip_not_terminal(trip)
    if trip["posture"] != "RECOVERING":
        raise ApiError("ERR_INVALID_STATE", 409, "Trip must be RECOVERING to close")
    if any(s["status"] not in ("DELIVERED", "LOST") for s in calc.trip_shipments(trip)):
        raise ApiError("ERR_INVALID_STATE", 409, "All equipment shipments must be DELIVERED or LOST")
    if any(l["status"] not in ("PAID", "ADJUSTED") for l in calc.trip_ledgers(trip)):
        raise ApiError("ERR_INVALID_STATE", 409, "All per-diem ledgers must be PAID or ADJUSTED")
    if any(c["status"] not in ("APPROVED", "DENIED", "REVOKED") for c in calc.trip_credentials(trip)):
        raise ApiError("ERR_INVALID_STATE", 409, "All credential requests must be APPROVED, DENIED or REVOKED")
    if any(e["status"] not in ("RESOLVED", "CLOSED") for e in calc.trip_events(trip)):
        raise ApiError("ERR_INVALID_STATE", 409, "All contingency events must be RESOLVED or CLOSED")
    trip["actual_cost_cents"] = calc.actual_cost_from_log(trip)
    trip["posture"] = "CLOSED"
    bump(trip)
    return ok(public(trip), 200)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/cancel", methods=["POST"])
def cancel_trip(teamId, tripId):
    require_role("TravelManager")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    body()
    trip_not_terminal(trip)
    if trip["posture"] not in ("DRAFT", "DISRUPTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Trip cannot be cancelled from current posture")
    if trip["posture"] == "DISRUPTED":
        if any(l["status"] == "DEPARTED" for l in calc.trip_legs(trip)):
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot cancel: a flight leg has DEPARTED")
        # Cancel active-pipeline contracts with penalty; cascade to legs/entries.
        for c in calc.trip_contracts(trip):
            if c["status"] in ("SUBMITTED", "VENDOR_COUNTERSIGNED", "TEAM_EXECUTED", "ACTIVE"):
                penalty = calc.cancellation_penalty(c, trip, clock_now())
                c["status"] = "CANCELLED"
                c["cancelled_at"] = fmt_ts(clock_now())
                c["cancellation_penalty_cents"] = penalty
                bump(c)
                amount = penalty if c.get("executed_at") is None else (
                    penalty - c["base_price_cents"] - c["fuel_surcharge_cap_cents"]
                )
                calc.log_financial_event(trip, fmt_ts(clock_now()), amount)
                for leg in calc.trip_legs(trip):
                    if leg.get("contract_id") == c["id"] and leg["status"] in (
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
        # Hotel blocks close; rooms_released = room_count - occupied.
        for b in calc.trip_blocks(trip):
            if b["posture"] != "CLOSED":
                b["rooms_released"] = b["room_count"] - calc.occupied_rooms(b)
                b["posture"] = "CLOSED"
                bump(b)
        # Draft per-diem rows adjusted to zero.
        for l in calc.trip_ledgers(trip):
            if l["status"] == "DRAFT":
                l["status"] = "ADJUSTED"
                l["net_amount_cents"] = 0
                bump(l)
        # Costs already incurred survive the cancellation (computed after the
        # contract cancellations so their penalties are included).
        trip["_incurred_loss_cents"] = calc.incurred_loss_cents(trip)
        season = STORE["seasons"][trip["season_id"]]
        bump(season)
    trip["posture"] = "CANCELLED"
    bump(trip)
    finalize_trip(trip)
    return ok(public(trip), 200)


# ---------------------------------------------------------------------------
# Travel party members
# ---------------------------------------------------------------------------
@bp.route("/travel/teams/<teamId>/trips/<tripId>/members", methods=["POST"])
def add_member(teamId, tripId):
    require_role("TravelManager")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    data = body()
    member_ref = req_str(data, "member_ref")
    party_role = req_enum(data, "party_role", calc.PARTY_ROLES)
    travel_class = req_enum(data, "travel_class", calc.TRAVEL_CLASSES)
    per_diem_tier = req_enum(data, "per_diem_tier", calc.PER_DIEM_TIERS)
    single = opt_bool(data, "requires_single_room", False)
    ground = opt_bool(data, "requires_ground_transport", True)
    trip_must_be_draft(trip)
    member = new_resource()
    member.update(
        {
            "trip_id": trip["id"],
            "member_ref": member_ref,
            "party_role": party_role,
            "travel_class": travel_class,
            "per_diem_tier": per_diem_tier,
            "requires_single_room": single,
            "requires_ground_transport": ground,
            "status": "IN",
            "weight_class": calc.weight_class_for(party_role),
            "_kind": "member",
        }
    )
    STORE["members"][member["id"]] = member
    finalize_trip(trip, enumerated=True)
    return ok(public(member), 201)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/members/<memberId>", methods=["GET"])
def get_member(teamId, tripId, memberId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    member = resolve_member(trip, memberId)
    team_member_read_guard(member)
    return ok(public(member), 200)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/members", methods=["GET"])
def list_members(teamId, tripId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    items = calc.trip_members(trip)
    if g.user_role == "TeamMember":
        items = [m for m in items if m["id"] == g.user_id]
    items = apply_filters(items, ["status"])
    page, total, limit, offset = paginate(items)
    return ok_list([public(m) for m in page], total, limit, offset)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/members/<memberId>/scratch", methods=["POST"])
def scratch_member(teamId, tripId, memberId):
    require_role("TravelManager")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    member = resolve_member(trip, memberId)
    body()
    trip_not_terminal(trip)
    if member["status"] != "IN":
        raise ApiError("ERR_INVALID_STATE", 409, "Member must be IN to scratch")
    member["status"] = "SCRATCHED"
    bump(member)
    # Cascade: manifest entries bumped MEDICAL_SCRATCH.
    for entry in STORE["entries"].values():
        if entry["member_id"] == member["id"] and entry["status"] in ("PENDING", "CONFIRMED"):
            entry["status"] = "BUMPED"
            entry["bump_reason"] = "MEDICAL_SCRATCH"
            bump(entry)
    # Cascade: room assignments cancelled (as primary occupant or roommate).
    for room in STORE["rooms"].values():
        if (
            room["member_id"] == member["id"] or room.get("roommate_member_id") == member["id"]
        ) and room["status"] in ("RESERVED", "CONFIRMED"):
            room["status"] = "CANCELLED"
            bump(room)
    # Cascade: draft per-diem ledgers adjusted (zeroed).
    for ledger in STORE["ledgers"].values():
        if ledger["member_id"] == member["id"] and ledger["status"] == "DRAFT":
            ledger["status"] = "ADJUSTED"
            ledger["net_amount_cents"] = 0
            bump(ledger)
    finalize_trip(trip, enumerated=True)
    return ok(public(member), 200)
