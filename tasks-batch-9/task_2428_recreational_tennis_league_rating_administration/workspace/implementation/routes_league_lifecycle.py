"""The five league lifecycle transitions (PRD 3.4 and 3.9)."""

from flask import Blueprint

import credit
import derive
from auth import authenticate
from errors import ApiError
from response import object_response
from routes_common import ADMIN_ONLY, COORDINATOR_ONLY, found
from store import db, insert, new_id, now, parse_instant, public, touch
from validation import body, reject_unknown

bp = Blueprint("league_lifecycle", __name__)

LIVE_PARENT_STATUSES = ("DRAFT", "REGISTRATION_OPEN", "ROSTERS_LOCKED", "IN_PLAY", "PLAYOFFS")
OPEN_SCHEDULE_STATUSES = ("UNSCHEDULED", "SCHEDULED", "CONFIRMED", "PLAYED")
OPEN_RESULT_STATUSES = ("PENDING", "REPORTED", "DISPUTED")


def _still_open(match):
    """A fixture is settled once either dimension has reached a settled value:
    result VERIFIED/FINALIZED/VOIDED, or schedule DEFAULTED/CANCELLED (PRD 3.9)."""
    return (match.get("schedule_status") in OPEN_SCHEDULE_STATUSES
            and match.get("result_status") in OPEN_RESULT_STATUSES)


def _league_teams(league_id):
    return [t for t in db.teams.values() if t.get("league_id") == league_id]


def _league_matches(league_id):
    return [m for m in db.matches.values() if m.get("league_id") == league_id]


TERMINAL_LEAGUE_STATUSES = ("COMPLETED", "CANCELLED")


def _require_stage(league, stage, terminal_code=False):
    """A lifecycle action aimed at the wrong stage.

    PRD 2.9 reserves ERR_LEAGUE_ALREADY_TERMINAL (rank 23) for a league already at
    COMPLETED or CANCELLED, plus the two stage mismatches PRD 3.4/3.9 name for it
    (seeding off IN_PLAY, advancement off PLAYOFFS). Every other stage mismatch has
    no declared transition, so the generic rank-20 ERR_INVALID_STATE wins the ladder.
    """
    if league.get("status") == stage:
        return
    if terminal_code or league.get("status") in TERMINAL_LEAGUE_STATUSES:
        raise ApiError("ERR_LEAGUE_ALREADY_TERMINAL")
    raise ApiError("ERR_INVALID_STATE")


@bp.post("/leagues/<league_id>/open-registration")
def open_registration(league_id):
    authenticate(ADMIN_ONLY)
    league = found("leagues", league_id)
    reject_unknown(body(), set())
    _require_stage(league, "DRAFT")

    parent_id = league.get("parent_league_id")
    if parent_id:
        parent = db.leagues.get(parent_id)
        if parent is None or parent.get("status") not in LIVE_PARENT_STATUSES:
            raise ApiError("ERR_LEAGUE_ALREADY_TERMINAL")

    section = db.sections.get(league.get("section_id")) or {}
    if section.get("rating_period_status") != "OPEN_SEASON":
        raise ApiError("ERR_RATING_PERIOD_CLOSED")

    current = now()
    opens_at = parse_instant(league.get("registration_opens_at"))
    closes_at = parse_instant(league.get("registration_closes_at"))
    if current < opens_at or not current < closes_at:
        raise ApiError("ERR_OUTSIDE_REGISTRATION_WINDOW")

    league["status"] = "REGISTRATION_OPEN"
    touch(league)
    return object_response(public(league))


@bp.post("/leagues/<league_id>/lock-rosters")
def lock_rosters(league_id):
    authenticate(COORDINATOR_ONLY)
    league = found("leagues", league_id)
    reject_unknown(body(), set())
    _require_stage(league, "REGISTRATION_OPEN")

    if now() < parse_instant(league.get("roster_lock_at")):
        raise ApiError("ERR_INVALID_STATE")
    if (league.get("registered_team_count") or 0) < 2:
        raise ApiError("ERR_ROSTER_QUOTA_NOT_MET")

    affected = []
    for team in _league_teams(league_id):
        if team.get("status") != "REGISTERED":
            continue
        team["status"] = "ROSTER_LOCKED"
        touch(team)
        for spot in db.roster_spots.values():
            if spot.get("team_id") == team["id"] and spot.get("status") == "PENDING":
                spot["status"] = "REMOVED"
                spot["ineligible_reason"] = None
                touch(spot)
        affected.append(team)
    for team in affected:
        derive.recompute_team_roster(team)
    league["status"] = "ROSTERS_LOCKED"
    touch(league)
    derive.recompute_league_counters(league)
    return object_response(public(league))


@bp.post("/leagues/<league_id>/start-play")
def start_play(league_id):
    authenticate(COORDINATOR_ONLY)
    league = found("leagues", league_id)
    reject_unknown(body(), set())
    _require_stage(league, "ROSTERS_LOCKED")

    ready = [t for t in _league_teams(league_id)
             if t.get("status") == "ROSTER_LOCKED" and t.get("roster_compliant")]
    if len(ready) < 2:
        raise ApiError("ERR_ROSTER_QUOTA_NOT_MET")

    for team in ready:
        team["status"] = "IN_PLAY"
        touch(team)
    league["status"] = "IN_PLAY"
    touch(league)
    derive.recompute_league_counters(league)
    return object_response(public(league))


@bp.post("/leagues/<league_id>/seed-playoffs")
def seed_playoffs(league_id):
    authenticate(COORDINATOR_ONLY)
    league = found("leagues", league_id)
    reject_unknown(body(), set())
    _require_stage(league, "IN_PLAY", terminal_code=True)

    for match in _league_matches(league_id):
        if match.get("stage") != "REGULAR":
            continue
        if _still_open(match):
            raise ApiError("ERR_INVALID_STATE")

    in_play = [t for t in _league_teams(league_id) if t.get("status") == "IN_PLAY"]
    if not in_play:
        raise ApiError("ERR_TEAM_STATE_INVALID")

    candidates = credit.seeding_candidates(league)
    if len(candidates) < 2:
        raise ApiError("ERR_NO_PLAYOFF_ELIGIBLE_TEAMS")

    ordered = credit.rank_candidates(candidates)
    candidate_ids = set(t["id"] for t in ordered)
    for index, team in enumerate(ordered, start=1):
        if team.get("playoff_seed") != index:
            team["playoff_seed"] = index
            touch(team)
    for team in in_play:
        if team["id"] not in candidate_ids:
            team["status"] = "ELIMINATED"
            touch(team)
    for match in _league_matches(league_id):
        if match.get("stage") == "REGULAR" and match.get("result_status") == "VERIFIED":
            match["result_status"] = "FINALIZED"
            touch(match)

    league["status"] = "PLAYOFFS"
    touch(league)
    derive.recompute_league_counters(league)
    return object_response(public(league))


def reseed_league(league):
    """Recompute every playoff_seed of a league (forfeit correction, PRD 3.9)."""
    candidates = credit.seeding_candidates(league)
    ordered = credit.rank_candidates(candidates)
    ranked = {team["id"]: index for index, team in enumerate(ordered, start=1)}
    for team in _league_teams(league["id"]):
        wanted = ranked.get(team["id"])
        if team.get("playoff_seed") != wanted:
            team["playoff_seed"] = wanted
            touch(team)
    derive.recompute_league_counters(league)


@bp.post("/leagues/<league_id>/advance-teams")
def advance_teams(league_id):
    authenticate(COORDINATOR_ONLY)
    league = found("leagues", league_id)
    reject_unknown(body(), set())
    _require_stage(league, "PLAYOFFS", terminal_code=True)

    if (league.get("seeded_team_count") or 0) < 1:
        raise ApiError("ERR_NO_PLAYOFF_ELIGIBLE_TEAMS")

    for match in _league_matches(league_id):
        if match.get("stage") != "PLAYOFF":
            continue
        if _still_open(match):
            raise ApiError("ERR_INVALID_STATE")

    parent = db.leagues.get(league.get("parent_league_id")) if league.get("parent_league_id") else None
    seeded = sorted([t for t in _league_teams(league_id) if t.get("playoff_seed") is not None],
                    key=lambda t: t.get("playoff_seed"))
    promote_count = min(int(league.get("advancement_slots") or 0),
                        int(league.get("seeded_team_count") or 0))
    promoted = seeded[:promote_count]

    if parent is not None:
        if parent.get("status") != "REGISTRATION_OPEN":
            raise ApiError("ERR_LEAGUE_ALREADY_TERMINAL")
        if (parent.get("registered_team_count") or 0) + len(promoted) > int(parent.get("max_teams") or 0):
            raise ApiError("ERR_ADVANCEMENT_SLOTS_EXHAUSTED")

    for team in promoted:
        team["status"] = "ADVANCED"
        touch(team)
        if parent is None:
            continue
        new_team = {
            "id": new_id(),
            "league_id": parent["id"],
            "captain_player_id": team.get("captain_player_id"),
            "name": team.get("name"),
            "home_facility_id": team.get("home_facility_id"),
            "advanced_from_team_id": team["id"],
            "status": "REGISTERED",
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
        insert("teams", new_team)
        for spot in sorted([s for s in db.roster_spots.values()
                            if s.get("team_id") == team["id"] and s.get("status") == "ACTIVE"],
                           key=lambda s: (s.get("created_at") or "", s.get("_seq") or 0)):
            insert("roster_spots", {
                "id": new_id(),
                "team_id": new_team["id"],
                "player_id": spot.get("player_id"),
                "status": "PENDING",
                "level_at_add": None,
                "verified_match_count": 0,
                "playoff_eligible": False,
                "ineligible_reason": None,
                "source_strike_id": None,
            })
        derive.recompute_team_roster(new_team)

    promoted_ids = set(t["id"] for t in promoted)
    for team in seeded:
        if team["id"] not in promoted_ids:
            team["status"] = "ELIMINATED"
            touch(team)

    if parent is not None:
        derive.recompute_league_counters(parent)
    league["status"] = "COMPLETED"
    touch(league)
    derive.recompute_league_counters(league)
    return object_response(public(league))
