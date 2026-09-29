"""Roster spots: concurrency-guarded add, the activation gates and captain removal."""

from decimal import Decimal

from flask import Blueprint

import derive
from auth import authenticate, require_team_captain
from errors import ApiError
from response import no_content_response, object_response
from routes_common import ALL_ROLES, CAPTAIN_ONLY, found, listing, reference
from store import db, insert, new_id, public, touch
from validation import as_int, body, present, reject_unknown, req_string

bp = Blueprint("roster", __name__)

AGE_MINIMUMS = {"AGE_18_OVER": 18, "AGE_40_OVER": 40, "AGE_55_OVER": 55}
LIVE_SPOT_STATUSES = ("PENDING", "ACTIVE", "INELIGIBLE")
FORMAT_GENDERS = {"MENS_DOUBLES": ("M",), "WOMENS_DOUBLES": ("F",),
                  "MIXED_DOUBLES": ("M", "F")}


def _league_of(team):
    return db.leagues.get(team.get("league_id")) or {}


def _section_of(team):
    return db.sections.get(_league_of(team).get("section_id")) or {}


def _roster_change_gates(team, league, section):
    if team.get("status") == "REGISTERED" and league.get("status") != "REGISTRATION_OPEN":
        raise ApiError("ERR_LEAGUE_PHASE_FORBIDS_ROSTER_CHANGE")
    if team.get("status") not in ("DRAFT", "REGISTERED"):
        raise ApiError("ERR_TEAM_STATE_INVALID")
    if section.get("rating_period_status") != "OPEN_SEASON":
        raise ApiError("ERR_RATING_PERIOD_CLOSED")


def _roster_headroom(team, league, extra=0):
    held = 0
    for spot in db.roster_spots.values():
        if spot.get("team_id") == team["id"] and spot.get("status") in ("PENDING", "ACTIVE"):
            held += 1
    if held + extra > int(league.get("max_roster_size") or 0):
        raise ApiError("ERR_ROSTER_SIZE_EXCEEDED")


@bp.post("/roster-spots")
def create_roster_spot():
    actor = authenticate(CAPTAIN_ONLY)
    payload = body()

    raw_team = payload.get("team_id")
    team = None
    if isinstance(raw_team, str) and raw_team.strip():
        team = reference("teams", raw_team.strip())
        require_team_captain(actor, team)
    raw_player = payload.get("player_id")
    player = None
    if isinstance(raw_player, str) and raw_player.strip():
        player = reference("players", raw_player.strip())
    if team is not None and player is not None:
        league = _league_of(team)
        if player.get("section_id") != league.get("section_id"):
            raise ApiError("ERR_SECTION_SCOPE_MISMATCH")

    reject_unknown(payload, {"team_id", "player_id", "expected_team_version"})
    req_string(payload, "team_id", 1)
    req_string(payload, "player_id", 1)
    if present(payload, "expected_team_version"):
        as_int(payload["expected_team_version"], "expected_team_version")
    if team is None or player is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")

    if not present(payload, "expected_team_version"):
        raise ApiError("ERR_MISSING_EXPECTED_VERSION")
    if int(payload["expected_team_version"]) != int(team.get("version")):
        raise ApiError("ERR_STALE_TEAM_VERSION")

    league = _league_of(team)
    section = _section_of(team)
    _roster_change_gates(team, league, section)

    for spot in db.roster_spots.values():
        if spot.get("player_id") != player["id"] or spot.get("status") not in LIVE_SPOT_STATUSES:
            continue
        other = db.teams.get(spot.get("team_id"))
        if other is not None and other.get("league_id") == league.get("id"):
            raise ApiError("ERR_DUPLICATE_ROSTER_SPOT")

    _roster_headroom(team, league, 1)

    record = {
        "id": new_id(),
        "team_id": team["id"],
        "player_id": player["id"],
        "status": "PENDING",
        "level_at_add": None,
        "verified_match_count": 0,
        "playoff_eligible": False,
        "ineligible_reason": None,
        "source_strike_id": None,
    }
    insert("roster_spots", record)
    touch(team)
    return object_response(public(record), 201)


@bp.get("/roster-spots/<spot_id>")
def get_roster_spot(spot_id):
    authenticate(ALL_ROLES)
    return object_response(public(found("roster_spots", spot_id)))


@bp.get("/roster-spots")
def list_roster_spots():
    authenticate(ALL_ROLES)
    spec = {"team_id": ("team_id", "str"), "player_id": ("player_id", "str"),
            "source_strike_id": ("source_strike_id", "str"), "status": ("status", "str"),
            "ineligible_reason": ("ineligible_reason", "str"),
            "playoff_eligible": ("playoff_eligible", "bool")}
    return listing(db.roster_spots.values(), spec)


@bp.post("/roster-spots/<spot_id>/activate")
def activate_roster_spot(spot_id):
    actor = authenticate(CAPTAIN_ONLY)
    spot = found("roster_spots", spot_id)
    team = db.teams.get(spot.get("team_id"))
    require_team_captain(actor, team)
    reject_unknown(body(), set())

    if spot.get("status") != "PENDING":
        raise ApiError("ERR_INVALID_STATE")

    league = _league_of(team)
    section = _section_of(team)
    _roster_change_gates(team, league, section)

    player = db.players.get(spot.get("player_id")) or {}
    if player.get("status") != "ACTIVE":
        raise ApiError("ERR_PLAYER_NOT_PLAYABLE")

    league_age = int(section.get("season_year") or 0) - int(player.get("birth_year") or 0)
    if league_age < AGE_MINIMUMS.get(league.get("age_group"), 0):
        raise ApiError("ERR_AGE_GROUP_NOT_MET")

    band = Decimal(str(league.get("ntrp_level")))
    if player.get("rating_type") == "UNRATED" or player.get("rating_level") is None:
        raise ApiError("ERR_RATING_LEVEL_EXCEEDS_LEAGUE")
    level = Decimal(str(player.get("rating_level")))
    if level > band or level < band - Decimal("1.0"):
        raise ApiError("ERR_RATING_LEVEL_EXCEEDS_LEAGUE")

    if player.get("gender") not in FORMAT_GENDERS.get(league.get("format"), ()):
        raise ApiError("ERR_FORMAT_GENDER_MISMATCH")

    _roster_headroom(team, league, 0)

    spot["status"] = "ACTIVE"
    spot["level_at_add"] = float(level)
    spot["ineligible_reason"] = None
    spot["source_strike_id"] = None
    touch(spot)
    derive.recompute_roster_spot(spot)
    derive.recompute_team_roster(team)
    derive.recompute_league_counters(league)
    return object_response(public(spot))


@bp.delete("/roster-spots/<spot_id>")
def remove_roster_spot(spot_id):
    actor = authenticate(CAPTAIN_ONLY)
    spot = found("roster_spots", spot_id)
    team = db.teams.get(spot.get("team_id"))
    require_team_captain(actor, team)

    if spot.get("status") not in ("PENDING", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE")
    league = _league_of(team)
    section = _section_of(team)
    if league.get("status") != "REGISTRATION_OPEN":
        raise ApiError("ERR_LEAGUE_PHASE_FORBIDS_ROSTER_CHANGE")
    if section.get("rating_period_status") != "OPEN_SEASON":
        raise ApiError("ERR_RATING_PERIOD_CLOSED")
    if (spot.get("verified_match_count") or 0) > 0:
        raise ApiError("ERR_ROSTER_SPOT_HAS_RESULTS")

    spot["status"] = "REMOVED"
    spot["ineligible_reason"] = None
    spot["source_strike_id"] = None
    touch(spot)
    # PRD 3.3: a successful removal "increases the team's `version` by 1", whether or
    # not the removed spot was ACTIVE and therefore changed a roster counter.
    touch(team)
    derive.recompute_team_roster(team)
    derive.recompute_league_counters(league)
    return no_content_response()
