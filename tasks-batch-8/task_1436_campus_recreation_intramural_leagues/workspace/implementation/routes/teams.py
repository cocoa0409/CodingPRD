"""Teams, division placement, reinstate/withdraw, roster entries."""

from flask import Blueprint, g, request

import errors as E
from domain import (team_out, roster_out, get_or_404, eligibility_gate,
                    apply_forfeit_effects)
from store import DB
from util import (body_json, req_str, req_int, envelope_object, list_response,
                  require_role, stamp_new, touch)

bp = Blueprint("teams", __name__)


@bp.route("/v1/teams", methods=["POST"])
def create_team():
    require_role("LeagueCoordinator")
    body = body_json()
    league_id = req_str(body, "league_id")
    captain_member_id = req_str(body, "captain_member_id")
    league = get_or_404(DB.leagues, league_id)
    get_or_404(DB.members, captain_member_id)
    name = req_str(body, "name")
    skill_rating = req_int(body, "skill_rating")
    if not (1 <= skill_rating <= 10):
        raise E.err_validation("skill_rating must be an integer in 1..10")
    if league["status"] != "REGISTRATION_OPEN":
        raise E.err_league_not_accepting()
    for t in DB.teams.values():
        if t["league_id"] == league_id and t["captain_member_id"] == captain_member_id \
           and t["status"] != "WITHDRAWN":
            raise E.err_team_already_in_league()
    non_withdrawn = sum(1 for t in DB.teams.values()
                        if t["league_id"] == league_id and t["status"] != "WITHDRAWN")
    if non_withdrawn >= league["team_capacity"]:
        raise E.err_league_full()
    team = stamp_new({
        "league_id": league_id,
        "name": name,
        "captain_member_id": captain_member_id,
        "skill_rating": skill_rating,
        "division_name": None,
        "status": "REGISTERED",
        "wins": 0,
        "losses": 0,
        "ties": 0,
        "points": 0,
        "forfeit_count": 0,
        "sportsmanship_points_total": 0,
        "sportsmanship_rating_count": 0,
        "sportsmanship_rating": None,
        "active_roster_count": 0,
    })
    DB.teams[team["id"]] = team
    return envelope_object(team_out(team), 201)


@bp.route("/v1/teams/<team_id>", methods=["GET"])
def get_team(team_id):
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    team = get_or_404(DB.teams, team_id)
    return envelope_object(team_out(team))


@bp.route("/v1/teams", methods=["GET"])
def list_teams():
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    league_id = request.args.get("league_id")
    captain = request.args.get("captain_member_id")
    division = request.args.get("division_name")
    status = request.args.get("status")
    records = [t for t in DB.teams.values()
               if (league_id is None or t["league_id"] == league_id)
               and (captain is None or t["captain_member_id"] == captain)
               and (division is None or t["division_name"] == division)
               and (status is None or t["status"] == status)]
    return list_response(records, team_out)


@bp.route("/v1/teams/<team_id>/place-division", methods=["POST"])
def place_division(team_id):
    require_role("LeagueCoordinator")
    team = get_or_404(DB.teams, team_id)
    body = body_json()
    league = DB.leagues.get(team["league_id"])
    division_name = req_str(body, "division_name")
    division = None
    if league is not None:
        for d in league["divisions"]:
            if d["name"] == division_name:
                division = d
                break
    if division is None:
        raise E.err_division_not_found()
    if league is None or league["status"] != "SCHEDULING":
        raise E.err_invalid_state("League must be in SCHEDULING to place teams")
    if team["status"] != "REGISTERED":
        raise E.err_invalid_state("Only a REGISTERED team can be placed")
    if not (division["skill_min"] <= team["skill_rating"] <= division["skill_max"]):
        raise E.err_division_skill_mismatch()
    in_division = sum(1 for t in DB.teams.values()
                      if t["league_id"] == league["id"]
                      and t["division_name"] == division_name
                      and t["status"] in ("PLACED", "ACTIVE", "SUSPENDED"))
    if in_division >= division["capacity"]:
        raise E.err_division_full()
    team["division_name"] = division_name
    team["status"] = "PLACED"
    touch(team)
    return envelope_object(team_out(team))


@bp.route("/v1/teams/<team_id>/reinstate", methods=["POST"])
def reinstate_team(team_id):
    require_role("LeagueCoordinator")
    team = get_or_404(DB.teams, team_id)
    league = DB.leagues.get(team["league_id"])
    if league is None or league["status"] != "IN_SEASON":
        raise E.err_invalid_state("League must be IN_SEASON to reinstate a team")
    if team["status"] != "SUSPENDED":
        raise E.err_invalid_state("Only a SUSPENDED team can be reinstated")
    team["status"] = "ACTIVE"
    touch(team)
    return envelope_object(team_out(team))


@bp.route("/v1/teams/<team_id>/withdraw", methods=["POST"])
def withdraw_team(team_id):
    require_role("Member", "LeagueCoordinator")
    team = get_or_404(DB.teams, team_id)
    if g.role == "Member" and team["captain_member_id"] != g.user_id:
        raise E.err_forbidden("Only the team captain may withdraw the team")
    if team["status"] not in ("REGISTERED", "PLACED", "ACTIVE", "SUSPENDED"):
        raise E.err_invalid_state("Team cannot be withdrawn from its current status")
    origin = team["status"]
    team["status"] = "WITHDRAWN"
    touch(team)
    if origin in ("ACTIVE", "SUSPENDED"):
        targets = [g for g in DB.games.values()
                   if g["status"] in ("SCHEDULED", "RESCHEDULE_REQUIRED")
                   and (g["home_team_id"] == team_id or g["away_team_id"] == team_id)]
        targets.sort(key=lambda g: g["_seq"])
        for g in targets:
            apply_forfeit_effects(g, team_id, manual=False)
    return envelope_object(team_out(team))


@bp.route("/v1/teams/<team_id>/roster-entries", methods=["POST"])
def add_roster_entry(team_id):
    require_role("Member")
    team = get_or_404(DB.teams, team_id)
    if team["captain_member_id"] != g.user_id:
        raise E.err_forbidden("Only the team captain may add roster entries")
    body = body_json()
    member_id = req_str(body, "member_id")
    member = get_or_404(DB.members, member_id)
    league = DB.leagues.get(team["league_id"])
    if league is None or league["status"] != "REGISTRATION_OPEN":
        raise E.err_league_not_accepting()
    if team["status"] not in ("REGISTERED", "PLACED"):
        raise E.err_invalid_state("Roster is locked")
    eligibility_gate(member)
    league_team_ids = {t["id"] for t in DB.teams.values() if t["league_id"] == team["league_id"]}
    for r in DB.roster_entries.values():
        if r["member_id"] == member_id and r["status"] == "ACTIVE" and r["team_id"] in league_team_ids:
            raise E.err_member_already_in_league()
    if team["active_roster_count"] >= league["roster_max"]:
        raise E.err_roster_full()
    role = "CAPTAIN" if member_id == team["captain_member_id"] else "PLAYER"
    entry = stamp_new({
        "team_id": team_id,
        "member_id": member_id,
        "role": role,
        "status": "ACTIVE",
    })
    DB.roster_entries[entry["id"]] = entry
    team["active_roster_count"] += 1
    touch(team)
    return envelope_object(roster_out(entry), 201)


@bp.route("/v1/roster-entries/<roster_entry_id>", methods=["GET"])
def get_roster_entry(roster_entry_id):
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    entry = get_or_404(DB.roster_entries, roster_entry_id)
    return envelope_object(roster_out(entry))


@bp.route("/v1/roster-entries", methods=["GET"])
def list_roster_entries():
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    team_id = request.args.get("team_id")
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    records = [r for r in DB.roster_entries.values()
               if (team_id is None or r["team_id"] == team_id)
               and (member_id is None or r["member_id"] == member_id)
               and (status is None or r["status"] == status)]
    return list_response(records, roster_out)


@bp.route("/v1/roster-entries/<roster_entry_id>/remove", methods=["POST"])
def remove_roster_entry(roster_entry_id):
    require_role("Member", "LeagueCoordinator")
    entry = get_or_404(DB.roster_entries, roster_entry_id)
    team = DB.teams.get(entry["team_id"])
    if g.role == "Member" and (team is None or team["captain_member_id"] != g.user_id):
        raise E.err_forbidden("Only the team captain may remove roster entries")
    if entry["status"] != "ACTIVE":
        raise E.err_invalid_state("Only an ACTIVE roster entry can be removed")
    if team is None or team["status"] not in ("REGISTERED", "PLACED"):
        raise E.err_invalid_state("Roster is locked")
    if team is not None and entry["member_id"] == team["captain_member_id"]:
        raise E.err_captain_removal()
    entry["status"] = "REMOVED"
    touch(entry)
    team["active_roster_count"] -= 1
    touch(team)
    return envelope_object(roster_out(entry))
