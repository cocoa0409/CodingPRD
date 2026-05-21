"""Waiver claim submission, cancellation, and sweep processing."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.errors import (
    err_faab_insufficient,
    err_invalid_state,
    err_not_team_owner,
    err_player_already_rostered,
    err_player_not_in_waivers,
    err_reference_not_found,
    err_resource_not_found,
    err_roster_full,
    err_validation,
    err_waiver_settle_in_past,
)
from core.store import store
from core.utils import format_iso, parse_iso
from services.timestamps import stamp_create, stamp_update


def _priority_seed_for_team(league_id: str, team_id: str) -> int:
    """Inverse-standings seed (worst record = 1).

    During regular season, derived from wins ascending; ties broken by points_for asc.
    Before regular season starts, derived from team creation order (first team = 1).
    """
    teams = store.teams_in_league(league_id)
    teams_sorted = sorted(
        teams, key=lambda t: (t.get("wins", 0), t.get("points_for", 0), t["created_at"])
    )
    for idx, t in enumerate(teams_sorted, start=1):
        if t["id"] == team_id:
            return idx
    return 1


def submit_claim(league_id: str, body: Dict[str, Any], acting_user_id: str) -> Dict[str, Any]:
    from services.league_service import get_league
    league = get_league(league_id)
    team_id = body.get("team_id")
    if not team_id:
        raise err_validation("team_id required.")
    team = store.teams.get(team_id)
    if not team or team["league_id"] != league_id:
        raise err_reference_not_found(f"Team {team_id} not in league.")
    if team["manager_user_id"] != acting_user_id:
        raise err_not_team_owner()

    add_player_id = body.get("add_player_id")
    if not add_player_id:
        raise err_validation("add_player_id required.")
    if add_player_id not in store.players:
        raise err_reference_not_found(f"Player {add_player_id} not found.")

    drop_player_id = body.get("drop_player_id")
    if drop_player_id is not None and drop_player_id not in store.players:
        raise err_reference_not_found(f"Drop player {drop_player_id} not found.")

    bid_dollars = body.get("bid_dollars")
    if not isinstance(bid_dollars, int) or isinstance(bid_dollars, bool) or bid_dollars < 0:
        raise err_validation("bid_dollars must be a non-negative integer.")

    settle_ts_raw = body.get("settle_ts")
    if not settle_ts_raw:
        raise err_validation("settle_ts required.")
    try:
        settle_dt = parse_iso(settle_ts_raw)
    except ValueError:
        raise err_validation(f"Invalid settle_ts: {settle_ts_raw}.")

    now_dt = parse_iso(league["now_ts"])
    if settle_dt <= now_dt:
        raise err_waiver_settle_in_past()

    # Player not on any roster in this league
    if store.player_team_in_league(league_id, add_player_id) is not None:
        raise err_player_already_rostered()

    # Player not in waivers period (only when waiver_period_hours > 0)
    if league["waiver_period_hours"] > 0:
        player = store.players[add_player_id]
        in_waivers = False
        if player["status_tag"] == "OUT":
            in_waivers = True
        else:
            # Check drop history within last waiver_period_hours
            drops = store.drop_history.get(league_id, [])
            for pid, dropped_at_iso in drops:
                if pid != add_player_id:
                    continue
                dropped_dt = parse_iso(dropped_at_iso)
                hours_since = (now_dt - dropped_dt).total_seconds() / 3600.0
                if hours_since <= league["waiver_period_hours"]:
                    in_waivers = True
                    break
        if not in_waivers:
            raise err_player_not_in_waivers()

    # FAAB sufficient at submission
    if bid_dollars > team["faab_balance_dollars"]:
        raise err_faab_insufficient()

    # Roster size check when no drop
    if drop_player_id is None:
        slots = store.roster_slots_for_team(team_id)
        if len(slots) >= league["roster_size"]:
            raise err_roster_full()

    priority_seed = _priority_seed_for_team(league_id, team_id)
    claim = {
        "league_id": league_id,
        "team_id": team_id,
        "add_player_id": add_player_id,
        "drop_player_id": drop_player_id,
        "bid_dollars": bid_dollars,
        "priority_seed": priority_seed,
        "status": "PENDING",
        "settle_ts": format_iso(settle_dt),
    }
    stamp_create(claim)
    store.waiver_claims[claim["id"]] = claim
    return claim


def list_claims(league_id: str, team_id: Optional[str] = None, status: Optional[str] = None) -> List[Dict[str, Any]]:
    from services.league_service import get_league
    get_league(league_id)
    items = [c for c in store.waiver_claims.values() if c["league_id"] == league_id]
    if team_id:
        items = [c for c in items if c["team_id"] == team_id]
    if status:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda x: x["created_at"])
    return items


def cancel_claim(claim_id: str, acting_user_id: str) -> Dict[str, Any]:
    claim = store.waiver_claims.get(claim_id)
    if not claim:
        raise err_resource_not_found(f"WaiverClaim {claim_id} not found.")
    team = store.teams.get(claim["team_id"])
    if not team or team["manager_user_id"] != acting_user_id:
        raise err_not_team_owner()
    if claim["status"] != "PENDING":
        raise err_invalid_state(f"Claim not PENDING (current={claim['status']}).")

    league = store.leagues.get(claim["league_id"])
    now_dt = parse_iso(league["now_ts"])
    settle_dt = parse_iso(claim["settle_ts"])
    if now_dt >= settle_dt:
        raise err_invalid_state("Cannot cancel after settle_ts has been reached.")

    claim["status"] = "CANCELED"
    stamp_update(claim)
    return claim


def process_due(league: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Run the waiver sweep for claims whose settle_ts <= league.now_ts."""
    return _sweep(league)


def process_now(league_id: str) -> List[Dict[str, Any]]:
    from services.league_service import get_league
    league = get_league(league_id)
    return _sweep(league)


def _sweep(league: Dict[str, Any]) -> List[Dict[str, Any]]:
    now_dt = parse_iso(league["now_ts"])
    eligible = [
        c
        for c in store.waiver_claims.values()
        if c["league_id"] == league["id"]
        and c["status"] == "PENDING"
        and parse_iso(c["settle_ts"]) <= now_dt
    ]
    # Group by add_player_id
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for c in eligible:
        groups.setdefault(c["add_player_id"], []).append(c)

    awarded = []
    for player_id, claims in groups.items():
        # Player still free agent?
        if store.player_team_in_league(league["id"], player_id) is not None:
            # All claims LOST
            for c in claims:
                if c["status"] == "PENDING":
                    c["status"] = "LOST"
                    stamp_update(c)
            continue

        claims_sorted = sorted(
            claims,
            key=lambda c: (-c["bid_dollars"], c["priority_seed"], c["created_at"]),
        )
        winner = None
        for c in claims_sorted:
            team = store.teams.get(c["team_id"])
            if not team:
                continue
            if team["faab_balance_dollars"] < c["bid_dollars"]:
                continue
            roster_count = len(store.roster_slots_for_team(team["id"]))
            if roster_count >= league["roster_size"] and c["drop_player_id"] is None:
                continue
            winner = c
            break

        if winner is None:
            continue

        # Award
        team = store.teams[winner["team_id"]]
        team["faab_balance_dollars"] -= winner["bid_dollars"]
        stamp_update(team)

        if winner["drop_player_id"]:
            # Remove existing slot for drop_player_id on this team
            slots = list(store.roster_slots_for_team(team["id"]))
            for s in slots:
                if s["player_id"] == winner["drop_player_id"]:
                    del store.roster_slots[s["id"]]
                    store.drop_history.setdefault(league["id"], []).append(
                        (winner["drop_player_id"], league["now_ts"])
                    )
                    break

        # Insert new BENCH slot
        from services.roster_service import insert_bench_slot
        insert_bench_slot(team["id"], winner["add_player_id"])

        winner["status"] = "AWARDED"
        stamp_update(winner)
        awarded.append(winner)

        # Mark every other PENDING claim for this player LOST
        for other in claims_sorted:
            if other["id"] != winner["id"] and other["status"] == "PENDING":
                other["status"] = "LOST"
                stamp_update(other)

    return awarded
