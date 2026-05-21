"""Keeper designation handling and price/round computation."""
from __future__ import annotations

import math
from typing import Any, Dict, List

from core.errors import (
    err_invalid_state,
    err_keeper_cap_exceeded,
    err_not_team_owner,
    err_reference_not_found,
    err_resource_not_found,
    err_validation,
)
from core.store import store
from services.player_service import get_player
from services.team_service import get_team
from services.timestamps import stamp_create, stamp_update


def lookup_prior_round(league: Dict[str, Any], team_id: str, player_id: str):
    """Returns prior-season round or None.

    For this implementation, we'll mimic a "no prior season DraftPick" scenario
    unless one exists in the store from a previous season-year. We look across all
    DraftPick rows where the parent league has season_year == league.season_year-1.
    """
    target_year = league["season_year"] - 1
    for pick in store.draft_picks.values():
        parent_league = store.leagues.get(pick["league_id"])
        if not parent_league or parent_league["season_year"] != target_year:
            continue
        if pick["team_id"] != team_id or pick["player_id"] != player_id:
            continue
        return pick.get("round_number", 0)
    return None


def lookup_prior_price(league: Dict[str, Any], team_id: str, player_id: str):
    target_year = league["season_year"] - 1
    for pick in store.draft_picks.values():
        parent_league = store.leagues.get(pick["league_id"])
        if not parent_league or parent_league["season_year"] != target_year:
            continue
        if pick["team_id"] != team_id or pick["player_id"] != player_id:
            continue
        return pick.get("price_dollars", 0)
    return None


def keeper_snake_round(league: Dict[str, Any], team_id: str, player_id: str) -> int:
    prior = lookup_prior_round(league, team_id, player_id)
    if prior is None:
        prior_round = league["regular_season_weeks"] + 5
    else:
        prior_round = prior
    return max(1, prior_round - 1)


def keeper_auction_price(league: Dict[str, Any], team_id: str, player_id: str) -> int:
    prior = lookup_prior_price(league, team_id, player_id)
    if prior is None or prior == 0:
        return 1
    # Multiply then ceiling
    product = prior * 1.10
    val = math.ceil(product)
    return max(1, val)


def declare_keeper(team_id: str, body: Dict[str, Any], acting_user_id: str) -> Dict[str, Any]:
    team = get_team(team_id)
    league = store.leagues.get(team["league_id"])
    if not league:
        raise err_resource_not_found("League not found.")
    if league["status"] != "DRAFT_PENDING":
        raise err_invalid_state(
            f"Cannot declare keeper outside DRAFT_PENDING (current={league['status']})."
        )
    if team["manager_user_id"] != acting_user_id:
        raise err_not_team_owner()

    player_id = body.get("player_id")
    if not player_id:
        raise err_validation("player_id required.")
    if player_id not in store.players:
        raise err_reference_not_found(f"Player {player_id} not found.")

    season_year = body.get("season_year")
    if season_year != league["season_year"]:
        raise err_validation(
            f"season_year must equal league.season_year ({league['season_year']})."
        )

    # Cap check
    existing = [
        k
        for k in store.keepers_for_team(team_id)
        if k["status"] in {"DECLARED", "LOCKED"}
    ]
    if len(existing) >= league["keeper_cap"]:
        raise err_keeper_cap_exceeded()

    if league["draft_mode"] == "SNAKE":
        assigned_round = keeper_snake_round(league, team_id, player_id)
        assigned_price = None
    else:
        assigned_price = keeper_auction_price(league, team_id, player_id)
        assigned_round = None

    keeper = {
        "league_id": league["id"],
        "team_id": team_id,
        "player_id": player_id,
        "season_year": season_year,
        "assigned_round": assigned_round,
        "assigned_price_dollars": assigned_price,
        "status": "DECLARED",
    }
    stamp_create(keeper)
    store.keeper_designations[keeper["id"]] = keeper
    return keeper


def list_keepers(team_id: str) -> List[Dict[str, Any]]:
    get_team(team_id)
    items = store.keepers_for_team(team_id)
    items.sort(key=lambda x: x["created_at"])
    return items


def revoke_keeper(team_id: str, keeper_id: str, acting_user_id: str) -> Dict[str, Any]:
    team = get_team(team_id)
    keeper = store.keeper_designations.get(keeper_id)
    if not keeper or keeper["team_id"] != team_id:
        raise err_resource_not_found(f"KeeperDesignation {keeper_id} not found.")
    league = store.leagues.get(keeper["league_id"])
    if not league:
        raise err_resource_not_found("League not found.")
    if team["manager_user_id"] != acting_user_id:
        raise err_not_team_owner()
    if league["status"] != "DRAFT_PENDING":
        raise err_invalid_state(
            f"Cannot revoke keeper outside DRAFT_PENDING (current={league['status']})."
        )
    if keeper["status"] != "DECLARED":
        raise err_invalid_state(
            f"Keeper not in DECLARED state (current={keeper['status']})."
        )
    keeper["status"] = "REVOKED"
    stamp_update(keeper)
    return keeper


def lock_declared_keepers(league: Dict[str, Any]) -> None:
    """Called at DRAFT_PENDING -> DRAFTING transition."""
    from services import draft_service

    teams = store.teams_in_league(league["id"])
    team_by_id = {t["id"]: t for t in teams}
    keepers = [
        k
        for k in store.keeper_designations.values()
        if k["league_id"] == league["id"] and k["status"] == "DECLARED"
    ]
    for keeper in keepers:
        keeper["status"] = "LOCKED"
        if league["draft_mode"] == "AUCTION":
            price = keeper_auction_price(league, keeper["team_id"], keeper["player_id"])
            keeper["assigned_price_dollars"] = price
            team = team_by_id[keeper["team_id"]]
            team["auction_balance_dollars"] = team["auction_balance_dollars"] - price
            stamp_update(team)
        else:
            assigned_round = keeper_snake_round(
                league, keeper["team_id"], keeper["player_id"]
            )
            keeper["assigned_round"] = assigned_round
            # Insert a DraftPick row for keeper
            draft_service.insert_keeper_pick(
                league, keeper["team_id"], keeper["player_id"], assigned_round
            )
        stamp_update(keeper)
