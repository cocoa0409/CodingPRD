"""Team CRUD."""
from __future__ import annotations

from typing import Any, Dict, List

from core.errors import (
    err_invalid_state,
    err_reference_not_found,
    err_resource_not_found,
    err_validation,
)
from core.store import store
from services.league_service import get_league
from services.timestamps import stamp_create


def create_team(league_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    league = get_league(league_id)
    if league["status"] != "DRAFT_PENDING":
        raise err_invalid_state(
            f"Cannot create team in league with status {league['status']}."
        )
    name = body.get("name")
    if not isinstance(name, str) or len(name) < 1 or len(name) > 60:
        raise err_validation("Team name must be 1..60 chars.")
    manager_user_id = body.get("manager_user_id")
    if not isinstance(manager_user_id, str) or not manager_user_id:
        raise err_validation("manager_user_id required.")

    # Uniqueness of name within league
    for t in store.teams_in_league(league_id):
        if t["name"] == name:
            raise err_validation("Team name must be unique within league.")

    team = {
        "league_id": league_id,
        "name": name,
        "manager_user_id": manager_user_id,
        "draft_position": None,
        "faab_balance_dollars": league["faab_budget_dollars"],
        "auction_balance_dollars": 0,
        "wins": 0,
        "losses": 0,
        "points_for": 0,
        "standing_seed": None,
    }
    stamp_create(team)
    store.teams[team["id"]] = team
    return team


def get_team(team_id: str) -> Dict[str, Any]:
    team = store.teams.get(team_id)
    if not team:
        raise err_resource_not_found(f"Team {team_id} not found.")
    return team


def get_team_in_league(league_id: str, team_id: str) -> Dict[str, Any]:
    # Verify league exists first
    get_league(league_id)
    team = store.teams.get(team_id)
    if not team or team["league_id"] != league_id:
        raise err_resource_not_found(f"Team {team_id} not in league {league_id}.")
    return team


def list_teams(league_id: str) -> List[Dict[str, Any]]:
    get_league(league_id)
    items = store.teams_in_league(league_id)
    items.sort(key=lambda x: x["created_at"])
    return items


def find_team_for_manager(league_id: str, manager_user_id: str):
    """Resolve the Team owned by a Manager user in a given league."""
    for t in store.teams_in_league(league_id):
        if t["manager_user_id"] == manager_user_id:
            return t
    return None
