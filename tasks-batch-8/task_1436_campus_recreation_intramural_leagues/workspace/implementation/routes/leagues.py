"""Leagues: creation, lifecycle transitions, free agents, playoff launch."""

from flask import Blueprint, g, request

import errors as E
from domain import (league_out, roster_out, get_or_404, eligibility_gate,
                    team_eligible, seed_division, cancel_assignment,
                    league_completion_check, SPORTS)
from store import DB
from util import (body_json, req_str, req_enum, req_int, req_dt, is_int,
                  envelope_object, require_role, stamp_new, touch, now)

bp = Blueprint("leagues", __name__)


def _validate_divisions(divisions):
    if not isinstance(divisions, list):
        raise E.err_validation("divisions must be an array")
    seen = set()
    for d in divisions:
        if not isinstance(d, dict):
            raise E.err_validation("each division must be an object")
        name = d.get("name")
        if not isinstance(name, str) or not name.strip():
            raise E.err_validation("division name must be a non-empty string")
        if name in seen:
            raise E.err_validation("division names must be unique within the league")
        seen.add(name)
        capacity = d.get("capacity")
        if not is_int(capacity) or capacity < 1:
            raise E.err_validation("division capacity must be an integer >= 1")
        skill_min = d.get("skill_min")
        skill_max = d.get("skill_max")
        if not is_int(skill_min) or not is_int(skill_max) or \
           not (1 <= skill_min <= skill_max <= 10):
            raise E.err_validation("division skill bounds must satisfy 1 <= skill_min <= skill_max <= 10")
    return [{"name": d["name"], "capacity": d["capacity"],
             "skill_min": d["skill_min"], "skill_max": d["skill_max"]} for d in divisions]


def _validate_league_window(league):
    if not (league["registration_open_at"] < league["registration_close_at"]
            <= league["season_start_at"] < league["season_end_at"]):
        raise E.err_validation("registration_open_at < registration_close_at <= season_start_at < season_end_at must hold")


@bp.route("/v1/leagues", methods=["POST"])
def create_league():
    require_role("RecAdmin")
    body = body_json()
    name = req_str(body, "name")
    sport = req_enum(body, "sport", SPORTS)
    if "divisions" not in body or body["divisions"] is None:
        raise E.err_validation("Missing required field: divisions")
    divisions = _validate_divisions(body["divisions"])
    reg_open = req_dt(body, "registration_open_at")
    reg_close = req_dt(body, "registration_close_at")
    season_start = req_dt(body, "season_start_at")
    season_end = req_dt(body, "season_end_at")
    team_capacity = req_int(body, "team_capacity")
    min_teams = req_int(body, "min_teams")
    roster_min = req_int(body, "roster_min")
    roster_max = req_int(body, "roster_max")
    if min_teams < 2:
        raise E.err_validation("min_teams must be >= 2")
    if team_capacity < min_teams:
        raise E.err_validation("team_capacity must be >= min_teams")
    if roster_min < 1:
        raise E.err_validation("roster_min must be >= 1")
    if roster_max < roster_min:
        raise E.err_validation("roster_max must be >= roster_min")
    league = stamp_new({
        "name": name,
        "sport": sport,
        "divisions": divisions,
        "registration_open_at": reg_open,
        "registration_close_at": reg_close,
        "season_start_at": season_start,
        "season_end_at": season_end,
        "team_capacity": team_capacity,
        "min_teams": min_teams,
        "roster_min": roster_min,
        "roster_max": roster_max,
        "status": "DRAFT",
        "free_agent_pool": [],
        "_brackets": [],
    })
    _validate_league_window(league)
    DB.leagues[league["id"]] = league
    return envelope_object(league_out(league), 201)


@bp.route("/v1/leagues/<league_id>", methods=["GET"])
def get_league(league_id):
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    league = get_or_404(DB.leagues, league_id)
    return envelope_object(league_out(league))


def _active_team_count(league_id):
    return sum(1 for t in DB.teams.values()
               if t["league_id"] == league_id and t["status"] in ("REGISTERED", "PLACED"))


@bp.route("/v1/leagues/<league_id>/open-registration", methods=["POST"])
def open_registration(league_id):
    require_role("LeagueCoordinator")
    league = get_or_404(DB.leagues, league_id)
    _validate_league_window(league)
    if league["status"] != "DRAFT":
        raise E.err_invalid_state("Registration can only be opened from DRAFT")
    if not league["divisions"]:
        raise E.err_league_not_ready("League has no divisions")
    league["status"] = "REGISTRATION_OPEN"
    touch(league)
    return envelope_object(league_out(league))


@bp.route("/v1/leagues/<league_id>/close-registration", methods=["POST"])
def close_registration(league_id):
    require_role("LeagueCoordinator")
    league = get_or_404(DB.leagues, league_id)
    if league["status"] != "REGISTRATION_OPEN":
        raise E.err_invalid_state("Registration can only be closed from REGISTRATION_OPEN")
    if _active_team_count(league_id) < league["min_teams"]:
        raise E.err_too_few_teams()
    league["status"] = "SCHEDULING"
    touch(league)
    return envelope_object(league_out(league))


@bp.route("/v1/leagues/<league_id>/start-season", methods=["POST"])
def start_season(league_id):
    require_role("LeagueCoordinator")
    league = get_or_404(DB.leagues, league_id)
    if league["status"] != "SCHEDULING":
        raise E.err_invalid_state("Season can only be started from SCHEDULING")
    teams = [t for t in DB.teams.values()
             if t["league_id"] == league_id and t["status"] in ("REGISTERED", "PLACED")]
    if len(teams) < league["min_teams"]:
        raise E.err_too_few_teams()
    for t in teams:
        if t["status"] != "PLACED" or t["division_name"] is None:
            raise E.err_league_not_ready("Every team must be placed in a division")
    for t in teams:
        if t["active_roster_count"] < league["roster_min"]:
            raise E.err_league_not_ready("Every team must meet roster_min")
    for t in teams:
        t["status"] = "ACTIVE"
        touch(t)
    league["status"] = "IN_SEASON"
    touch(league)
    return envelope_object(league_out(league))


@bp.route("/v1/leagues/<league_id>/start-playoffs", methods=["POST"])
def start_playoffs(league_id):
    require_role("LeagueCoordinator")
    league = get_or_404(DB.leagues, league_id)
    if league["status"] != "IN_SEASON":
        raise E.err_invalid_state("Playoffs can only be started from IN_SEASON")
    for g in DB.games.values():
        if g["league_id"] == league_id and g["status"] in (
                "SCHEDULED", "RESCHEDULE_REQUIRED", "PLAYED_PENDING_CONFIRM", "DISPUTED"):
            raise E.err_playoffs_not_ready()
    league_teams = [t for t in DB.teams.values() if t["league_id"] == league_id]
    eligible = [t for t in league_teams if team_eligible(t)]
    if len(eligible) < 2:
        raise E.err_no_eligible_teams()
    brackets = []
    for division in league["divisions"]:
        div_teams = [t for t in eligible if t["division_name"] == division["name"]]
        if len(div_teams) < 2:
            continue
        seeded = seed_division(div_teams, league_id)
        if len(seeded) >= 4:
            import uuid as _uuid
            group = _uuid.uuid4().hex
            sf_specs = [(0, 3), (1, 2)]  # seed1 home vs seed4 away; seed2 home vs seed3 away
            sf_ids = []
            for home_idx, away_idx in sf_specs:
                game = stamp_new({
                    "league_id": league_id,
                    "division_name": None,
                    "home_team_id": seeded[home_idx]["id"],
                    "away_team_id": seeded[away_idx]["id"],
                    "facility_id": None,
                    "start_at": None,
                    "end_at": None,
                    "duration_minutes": None,
                    "status": "RESCHEDULE_REQUIRED",
                    "bracket_round": "SEMIFINAL",
                    "next_game_id": None,
                    "report_home": None,
                    "report_away": None,
                    "final_home_score": None,
                    "final_away_score": None,
                    "actual_duration_minutes": None,
                    "forfeiting_team_id": None,
                    "_division": division["name"],
                    "_home_seed": home_idx + 1,
                    "_away_seed": away_idx + 1,
                    "_sf_group": group,
                })
                DB.games[game["id"]] = game
                sf_ids.append(game["id"])
            brackets.append({"division": division["name"], "sf_group": group,
                             "sf_ids": sf_ids, "championship_id": None})
        else:
            game = stamp_new({
                "league_id": league_id,
                "division_name": None,
                "home_team_id": seeded[0]["id"],
                "away_team_id": seeded[1]["id"],
                "facility_id": None,
                "start_at": None,
                "end_at": None,
                "duration_minutes": None,
                "status": "RESCHEDULE_REQUIRED",
                "bracket_round": "CHAMPIONSHIP",
                "next_game_id": None,
                "report_home": None,
                "report_away": None,
                "final_home_score": None,
                "final_away_score": None,
                "actual_duration_minutes": None,
                "forfeiting_team_id": None,
                "_division": division["name"],
                "_home_seed": 1,
                "_away_seed": 2,
                "_sf_group": None,
            })
            DB.games[game["id"]] = game
            brackets.append({"division": division["name"], "sf_group": None,
                             "sf_ids": [], "championship_id": game["id"]})
    league["_brackets"] = brackets
    league["status"] = "PLAYOFFS"
    touch(league)
    return envelope_object(league_out(league))


@bp.route("/v1/leagues/<league_id>/cancel", methods=["POST"])
def cancel_league(league_id):
    require_role("LeagueCoordinator")
    league = get_or_404(DB.leagues, league_id)
    if league["status"] not in ("DRAFT", "REGISTRATION_OPEN", "SCHEDULING", "IN_SEASON"):
        raise E.err_invalid_state("League cannot be cancelled from its current status")
    games = [g for g in DB.games.values()
             if g["league_id"] == league_id and g["status"] in (
                 "SCHEDULED", "RESCHEDULE_REQUIRED", "PLAYED_PENDING_CONFIRM", "DISPUTED")]
    for g in games:
        g["status"] = "CANCELLED"
        touch(g)
        for a in list(DB.assignments.values()):
            if a["game_id"] == g["id"]:
                cancel_assignment(a)
    for t in DB.teams.values():
        if t["league_id"] == league_id and t["status"] in (
                "REGISTERED", "PLACED", "ACTIVE", "SUSPENDED"):
            t["status"] = "WITHDRAWN"
            touch(t)
    for entry in league["free_agent_pool"]:
        if entry["status"] == "POOLED":
            entry["status"] = "WITHDRAWN"
    league["status"] = "CANCELLED"
    touch(league)
    return envelope_object(league_out(league))


@bp.route("/v1/leagues/<league_id>/free-agents", methods=["POST"])
def register_free_agent(league_id):
    require_role("Member")
    league = get_or_404(DB.leagues, league_id)
    body = body_json()
    if body.get("member_id") is not None and body["member_id"] != g.user_id:
        raise E.err_forbidden("Members may only register themselves as free agents")
    member_id = req_str(body, "member_id")
    if member_id != g.user_id:
        raise E.err_forbidden("Members may only register themselves as free agents")
    member = get_or_404(DB.members, member_id)
    preferred = body.get("preferred_division_name")
    if preferred is not None:
        if not isinstance(preferred, str) or not preferred.strip():
            raise E.err_validation("preferred_division_name must be a non-empty string")
        if not any(d["name"] == preferred for d in league["divisions"]):
            raise E.err_division_not_found()
    if league["status"] != "REGISTRATION_OPEN":
        raise E.err_league_not_accepting()
    eligibility_gate(member)
    league_team_ids = {t["id"] for t in DB.teams.values() if t["league_id"] == league_id}
    for r in DB.roster_entries.values():
        if r["member_id"] == member_id and r["status"] == "ACTIVE" and r["team_id"] in league_team_ids:
            raise E.err_member_already_in_league()
    for entry in league["free_agent_pool"]:
        if entry["member_id"] == member_id and entry["status"] == "POOLED":
            raise E.err_already_in_pool()
    league["free_agent_pool"].append({
        "member_id": member_id,
        "preferred_division_name": preferred,
        "registered_at": now(),
        "status": "POOLED",
    })
    touch(league)
    return envelope_object(league_out(league), 201)


@bp.route("/v1/leagues/<league_id>/place-free-agent", methods=["POST"])
def place_free_agent(league_id):
    require_role("LeagueCoordinator")
    league = get_or_404(DB.leagues, league_id)
    body = body_json()
    member_id = req_str(body, "member_id")
    get_or_404(DB.members, member_id)
    entry = None
    for e in league["free_agent_pool"]:
        if e["member_id"] == member_id and e["status"] == "POOLED":
            entry = e
            break
    if entry is None:
        if any(e["member_id"] == member_id for e in league["free_agent_pool"]):
            raise E.err_invalid_state("Free-agent pool entry is not POOLED")
        raise E.err_not_found("Member has no free-agent pool entry in this league")
    candidates = [t for t in DB.teams.values()
                  if t["league_id"] == league_id
                  and t["status"] in ("REGISTERED", "PLACED")
                  and t["active_roster_count"] < league["roster_max"]]
    if entry["preferred_division_name"] is not None:
        candidates = [t for t in candidates
                      if t["division_name"] == entry["preferred_division_name"]]
    if not candidates:
        raise E.err_no_team_available()
    candidates.sort(key=lambda t: (t["active_roster_count"], t["created_at"], t["_seq"]))
    team = candidates[0]
    roster = stamp_new({
        "team_id": team["id"],
        "member_id": member_id,
        "role": "PLAYER",
        "status": "ACTIVE",
    })
    DB.roster_entries[roster["id"]] = roster
    entry["status"] = "PLACED"
    team["active_roster_count"] += 1
    touch(team)
    touch(league)
    return envelope_object(roster_out(roster))
