"""Team endpoints: create, read, draft-pick."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_roles
from ..calculations import TIER_A_CAP, draft_seat_resolver
from ..errors import raise_error
from ..response import success_response
from ..services.aggregates import recompute_team_roster
from ..services.lookup import get_coach, get_player, get_season, get_team
from ..services.serializers import serialize_player, serialize_team
from ..store import get_store, new_id, stamp_create, stamp_update
from ..validation import as_int, as_string, get_json_body, require_fields

team_bp = Blueprint("teams", __name__)


@team_bp.route("/league/teams", methods=["POST"])
@require_roles(["LeagueAdmin"])
def create_team():
    body = get_json_body()
    require_fields(body, ["season_id", "name", "head_coach_id", "draft_position"])
    store = get_store()
    season = get_season(store, body["season_id"])
    coach = get_coach(store, body["head_coach_id"])

    name = as_string(body["name"], "name", min_len=1, max_len=80)
    draft_position = as_int(body["draft_position"], "draft_position", minimum=1, maximum=32)

    # Background check gate.
    if not coach.get("background_check_passed"):
        raise_error("ERR_COACH_NO_BACKGROUND_CHECK")

    # Uniqueness within season.
    for t in store.teams.values():
        if t["season_id"] == season["id"]:
            if t["name"] == name or t["draft_position"] == draft_position:
                raise_error("ERR_TEAM_DUPLICATE")

    team = {
        "id": new_id(),
        "season_id": season["id"],
        "name": name,
        "head_coach_id": coach["id"],
        "draft_position": draft_position,
        "roster_count": 0,
        "tier_a_count": 0,
        "wins": 0,
        "losses": 0,
        "playoff_seed": None,
        "playoff_status": "NOT_QUALIFIED",
    }
    stamp_create(team)
    store.teams[team["id"]] = team
    store.record_audit("Team", team["id"], g.role, g.user_id, "TEAM_CREATED", {})
    return success_response(serialize_team(team), status_code=201)


@team_bp.route("/league/teams/<team_id>", methods=["GET"])
@require_roles(["LeagueAdmin", "Coach", "Referee", "Guardian"])
def read_team(team_id: str):
    store = get_store()
    team = get_team(store, team_id)
    return success_response(serialize_team(team), status_code=200)


# ---------------------------------------------------------------------------
# draft-pick
# ---------------------------------------------------------------------------
@team_bp.route("/league/teams/<team_id>/draft-pick", methods=["POST"])
@require_roles(["Coach", "LeagueAdmin"])
def draft_pick(team_id: str):
    store = get_store()
    team = get_team(store, team_id)
    body = get_json_body()
    require_fields(body, ["player_id"])
    player = get_player(store, body["player_id"])

    season = get_season(store, team["season_id"])
    if season["status"] != "DRAFT_OPEN":
        raise_error("ERR_SEASON_NOT_DRAFT_OPEN")
    if player["status"] != "EVALUATED":
        raise_error("ERR_INVALID_PLAYER_STATE", "Player must be EVALUATED to be drafted.")

    # Coach ownership when acting as Coach.
    if g.role == "Coach" and g.user_id != team["head_coach_id"]:
        raise_error("ERR_NOT_TEAM_OWNER")

    # Snake-draft seat: must equal team.draft_position.
    teams_in_season = [t for t in store.teams.values() if t["season_id"] == season["id"]]
    expected_seat = draft_seat_resolver(season["id"], teams_in_season, store.players.values())
    if team["draft_position"] != expected_seat:
        raise_error("ERR_NOT_TEAMS_TURN")

    # Player must belong to the same season as the team.
    if player["season_id"] != team["season_id"]:
        raise_error("ERR_VALIDATION", "Player does not belong to the team's season.")

    # Tier-A cap.
    if team.get("tier_a_count", 0) >= TIER_A_CAP and player.get("evaluation_tier") == "TIER_A":
        raise_error("ERR_TIER_A_CAP_EXCEEDED")

    # Allocate the next overall pick number across this season.
    next_overall = (
        sum(
            1
            for p in store.players.values()
            if p["season_id"] == season["id"] and p.get("status") == "DRAFTED"
        )
        + 1
    )

    player["team_id"] = team["id"]
    player["draft_pick_overall"] = next_overall
    player["status"] = "DRAFTED"
    stamp_update(player)

    recompute_team_roster(store, team)

    store.record_audit(
        "Player",
        player["id"],
        g.role,
        g.user_id,
        "PLAYER_DRAFTED",
        {"team_id": team["id"], "pick_overall": next_overall},
    )
    return success_response(serialize_player(player), status_code=200)
