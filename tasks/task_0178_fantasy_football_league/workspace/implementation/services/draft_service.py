"""Draft pick submission."""
from __future__ import annotations

from typing import Any, Dict, List

from core.errors import (
    err_auction_budget_exceeded,
    err_invalid_state,
    err_not_team_owner,
    err_not_your_turn,
    err_player_already_drafted,
    err_position_ineligible,
    err_reference_not_found,
    err_resource_not_found,
    err_validation,
)
from core.store import store
from core.utils import new_id, now_iso
from services.league_service import get_league
from services.player_service import get_player


def insert_keeper_pick(league: Dict[str, Any], team_id: str, player_id: str, assigned_round: int):
    """Insert a draft pick for a locked keeper at start-draft time."""
    league_picks = store.draft_picks_in_league(league["id"])
    overall_index = len(league_picks) + 1
    pick = {
        "id": new_id(),
        "created_at": now_iso(),
        "league_id": league["id"],
        "team_id": team_id,
        "player_id": player_id,
        "round_number": assigned_round,
        "overall_pick_index": overall_index,
        "price_dollars": 0,
        "is_keeper": True,
    }
    store.draft_picks[pick["id"]] = pick
    return pick


def next_snake_turn(league: Dict[str, Any]) -> str:
    """Return the team_id whose turn it is in snake draft order."""
    teams = store.teams_in_league(league["id"])
    teams_sorted = sorted(teams, key=lambda t: t.get("draft_position") or 0)
    team_count = league["team_count"]

    # Count non-keeper picks made (those without is_keeper=true)
    picks = store.draft_picks_in_league(league["id"])
    non_keeper_picks = [p for p in picks if not p.get("is_keeper")]
    pick_index = len(non_keeper_picks)  # 0-based

    rounds_total = league["roster_size"] - league["ir_slots"]
    round_index = pick_index // team_count  # 0-based round
    position_in_round = pick_index % team_count  # 0-based

    if round_index >= rounds_total:
        return None  # draft full

    # Snake order: even rounds go forward, odd rounds reverse
    if round_index % 2 == 0:
        team = teams_sorted[position_in_round]
    else:
        team = teams_sorted[team_count - 1 - position_in_round]
    return team["id"]


def submit_pick(league_id: str, body: Dict[str, Any], acting_user_id: str) -> Dict[str, Any]:
    league = get_league(league_id)
    if league["status"] != "DRAFTING":
        raise err_invalid_state(
            f"Cannot draft outside DRAFTING (current={league['status']})."
        )
    team_id = body.get("team_id")
    if not team_id:
        raise err_validation("team_id required.")
    player_id = body.get("player_id")
    if not player_id:
        raise err_validation("player_id required.")
    team = store.teams.get(team_id)
    if not team or team["league_id"] != league_id:
        raise err_reference_not_found(f"Team {team_id} not found in league.")
    player = store.players.get(player_id)
    if not player:
        raise err_reference_not_found(f"Player {player_id} not found.")
    if team["manager_user_id"] != acting_user_id:
        raise err_not_team_owner()

    # Check for already-drafted player
    for p in store.draft_picks_in_league(league_id):
        if p["player_id"] == player_id:
            raise err_player_already_drafted()

    price = body.get("price_dollars", 0)
    if not isinstance(price, int) or isinstance(price, bool) or price < 0:
        raise err_validation("price_dollars must be a non-negative integer.")

    if league["draft_mode"] == "SNAKE":
        expected = next_snake_turn(league)
        if expected != team_id:
            raise err_not_your_turn()
        # auction balance not affected
        price = 0
    else:
        # AUCTION mode
        if price < 0:
            raise err_validation("price_dollars must be >= 0.")
        # Auction budget floor: remaining_required_picks - 1 dollars must remain after this pick
        team_picks = [
            p for p in store.draft_picks_in_league(league_id) if p["team_id"] == team_id
        ]
        rounds_total = league["roster_size"] - league["ir_slots"]
        remaining_required = rounds_total - len(team_picks)
        if price > team["auction_balance_dollars"] - (remaining_required - 1):
            raise err_auction_budget_exceeded()

    # Snake round and overall pick index
    picks_so_far = store.draft_picks_in_league(league_id)
    overall_pick_index = len(picks_so_far) + 1

    if league["draft_mode"] == "SNAKE":
        non_keeper_so_far = [p for p in picks_so_far if not p.get("is_keeper")]
        round_index = len(non_keeper_so_far) // league["team_count"]
        round_number = round_index + 1
    else:
        round_number = 0

    pick = {
        "id": new_id(),
        "created_at": now_iso(),
        "league_id": league_id,
        "team_id": team_id,
        "player_id": player_id,
        "round_number": round_number,
        "overall_pick_index": overall_pick_index,
        "price_dollars": price,
        "is_keeper": False,
    }
    store.draft_picks[pick["id"]] = pick

    # Decrement auction balance
    if league["draft_mode"] == "AUCTION" and price > 0:
        team["auction_balance_dollars"] -= price
        from services.timestamps import stamp_update
        stamp_update(team)

    return pick


def list_picks(league_id: str) -> List[Dict[str, Any]]:
    get_league(league_id)
    items = store.draft_picks_in_league(league_id)
    items.sort(key=lambda x: x.get("overall_pick_index", 0))
    return items
