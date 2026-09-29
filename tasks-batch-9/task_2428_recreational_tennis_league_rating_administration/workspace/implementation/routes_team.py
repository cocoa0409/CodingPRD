"""Teams: creation, reads, registration and the withdrawal cascade."""

from flask import Blueprint

import derive
from auth import authenticate, require_team_captain
from errors import ApiError
from response import object_response
from routes_common import ALL_ROLES, CAPTAIN_ONLY, found, listing, reference
from store import db, insert, new_id, now, parse_instant, public, touch
from validation import bad, body, opt_string, reject_unknown, req_string

import routes_roster as roster

bp = Blueprint("team", __name__, url_prefix="/tennis")
bp.register_blueprint(roster.bp)

CANCELLABLE_SCHEDULE_STATUSES = ("UNSCHEDULED", "SCHEDULED", "CONFIRMED")
WITHDRAW_LEAGUE_GATES = {
    "REGISTERED": ("REGISTRATION_OPEN", "ROSTERS_LOCKED", "IN_PLAY"),
    "ROSTER_LOCKED": ("ROSTERS_LOCKED", "IN_PLAY"),
    "IN_PLAY": ("IN_PLAY",),
}


@bp.post("/teams")
def create_team():
    actor = authenticate(CAPTAIN_ONLY)
    payload = body()

    raw_league = payload.get("league_id")
    league = None
    if isinstance(raw_league, str) and raw_league.strip():
        league = reference("leagues", raw_league.strip())
    raw_facility = payload.get("home_facility_id")
    facility = None
    if isinstance(raw_facility, str) and raw_facility.strip():
        facility = reference("facilities", raw_facility.strip())

    reject_unknown(payload, {"league_id", "name", "home_facility_id"})
    req_string(payload, "league_id", 1)
    name = req_string(payload, "name", 1)
    req_string(payload, "home_facility_id", 1)
    if league is None or facility is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")

    if facility.get("section_id") != league.get("section_id"):
        # PRD 2.10 scopes team creation, and rank 12 outranks rank 42 (PRD 2.9).
        raise ApiError("ERR_SECTION_SCOPE_MISMATCH")

    for existing in db.teams.values():
        if existing.get("league_id") == league["id"] and existing.get("name") == name:
            bad("Team name must be unique within the league.")

    record = {
        "id": new_id(),
        "league_id": league["id"],
        "captain_player_id": actor.user_id,
        "name": name,
        "home_facility_id": facility["id"],
        "advanced_from_team_id": None,
        "status": "DRAFT",
        "active_roster_size": 0,
        "playoff_eligible_roster_size": 0,
        "roster_compliant": False,
        "matches_won": 0,
        "matches_lost": 0,
        "lines_won": 0,
        "lines_lost": 0,
        "sets_won": 0,
        "sets_lost": 0,
        "games_won": 0,
        "games_lost": 0,
        "standings_points": 0,
        "playoff_seed": None,
    }
    insert("teams", record)
    return object_response(public(record), 201)


@bp.get("/teams/<team_id>")
def get_team(team_id):
    authenticate(ALL_ROLES)
    return object_response(public(found("teams", team_id)))


@bp.get("/teams")
def list_teams():
    authenticate(ALL_ROLES)
    spec = {"league_id": ("league_id", "str"), "captain_player_id": ("captain_player_id", "str"),
            "home_facility_id": ("home_facility_id", "str"),
            "advanced_from_team_id": ("advanced_from_team_id", "str"),
            "status": ("status", "str")}
    return listing(db.teams.values(), spec)


@bp.post("/teams/<team_id>/register")
def register_team(team_id):
    actor = authenticate(CAPTAIN_ONLY)
    team = found("teams", team_id)
    require_team_captain(actor, team)
    reject_unknown(body(), set())

    league = db.leagues.get(team.get("league_id")) or {}
    if league.get("status") != "REGISTRATION_OPEN":
        raise ApiError("ERR_LEAGUE_PHASE_FORBIDS_ROSTER_CHANGE")
    if team.get("status") != "DRAFT":
        raise ApiError("ERR_TEAM_STATE_INVALID")

    current = now()
    opens_at = parse_instant(league.get("registration_opens_at"))
    closes_at = parse_instant(league.get("registration_closes_at"))
    if current < opens_at or not current < closes_at:
        raise ApiError("ERR_OUTSIDE_REGISTRATION_WINDOW")
    if (league.get("registered_team_count") or 0) >= int(league.get("max_teams") or 0):
        raise ApiError("ERR_LEAGUE_TEAM_CAPACITY_REACHED")
    if (team.get("active_roster_size") or 0) < 2:
        raise ApiError("ERR_ROSTER_QUOTA_NOT_MET")

    team["status"] = "REGISTERED"
    touch(team)
    derive.recompute_league_counters(league)
    return object_response(public(team))


@bp.post("/teams/<team_id>/withdraw")
def withdraw_team(team_id):
    actor = authenticate(CAPTAIN_ONLY)
    team = found("teams", team_id)
    require_team_captain(actor, team)
    payload = body()
    reject_unknown(payload, {"reason"})
    opt_string(payload, "reason", None, 1)

    origin = team.get("status")
    if origin not in WITHDRAW_LEAGUE_GATES:
        # No withdrawal edge is declared from this state, and rank 20 outranks 31.
        raise ApiError("ERR_INVALID_STATE")
    league = db.leagues.get(team.get("league_id")) or {}
    if league.get("status") not in WITHDRAW_LEAGUE_GATES[origin]:
        raise ApiError("ERR_INVALID_STATE")
    if origin == "IN_PLAY":
        for match in db.matches.values():
            if team["id"] not in (match.get("home_team_id"), match.get("away_team_id")):
                continue
            if match.get("result_status") == "VERIFIED":
                raise ApiError("ERR_TEAM_HAS_VERIFIED_RESULTS")

    for spot in db.roster_spots.values():
        if spot.get("team_id") != team["id"]:
            continue
        if spot.get("status") in ("PENDING", "ACTIVE", "INELIGIBLE"):
            spot["status"] = "REMOVED"
            spot["ineligible_reason"] = None
            spot["source_strike_id"] = None
            touch(spot)
    for match in db.matches.values():
        if team["id"] not in (match.get("home_team_id"), match.get("away_team_id")):
            continue
        if (match.get("schedule_status") in CANCELLABLE_SCHEDULE_STATUSES
                and match.get("result_status") == "PENDING"):
            match["schedule_status"] = "CANCELLED"
            touch(match)

    team["status"] = "WITHDRAWN"
    touch(team)
    derive.recompute_team_roster(team)
    derive.recompute_league_counters(league)

    count = league.get("registered_team_count") or 0
    if count < 2 and league.get("status") == "ROSTERS_LOCKED":
        league["status"] = "REGISTRATION_OPEN"
        touch(league)
        for other in db.teams.values():
            if other.get("league_id") == league["id"] and other.get("status") == "ROSTER_LOCKED":
                other["status"] = "REGISTERED"
                touch(other)
    elif count == 0 and league.get("status") == "REGISTRATION_OPEN":
        league["status"] = "CANCELLED"
        touch(league)
        for match in db.matches.values():
            if match.get("league_id") != league["id"]:
                continue
            if match.get("schedule_status") in CANCELLABLE_SCHEDULE_STATUSES:
                match["schedule_status"] = "CANCELLED"
                touch(match)
    derive.recompute_league_counters(league)
    return object_response(public(team))
