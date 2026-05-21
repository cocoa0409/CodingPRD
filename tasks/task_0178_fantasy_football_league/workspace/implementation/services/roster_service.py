"""Roster slot management and lineup mutations."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.errors import (
    err_invalid_state,
    err_ir_ineligible,
    err_lineup_locked,
    err_not_team_owner,
    err_position_constraint,
    err_position_ineligible,
    err_resource_not_found,
    err_roster_shape_invalid,
    err_validation,
    err_version_conflict,
)
from core.store import store
from services.timestamps import stamp_create, stamp_update


VALID_SLOT_TYPES = {"STARTER", "BENCH", "IR"}
FLEX_POSITIONS = {"RB", "WR", "TE", "FLEX_RWT"}

# starter labels expected
DEFAULT_STARTER_LABELS = ["QB1", "RB1", "RB2", "WR1", "WR2", "WR3", "TE1", "FLEX", "K1", "DST1"]


def insert_bench_slot(team_id: str, player_id: str) -> Dict[str, Any]:
    slot = {
        "team_id": team_id,
        "player_id": player_id,
        "slot_type": "BENCH",
        "position_label": None,
        "locked_until_ts": None,
    }
    stamp_create(slot)
    store.roster_slots[slot["id"]] = slot
    return slot


def get_slot(slot_id: str) -> Dict[str, Any]:
    s = store.roster_slots.get(slot_id)
    if not s:
        raise err_resource_not_found(f"RosterSlot {slot_id} not found.")
    return s


def position_root(position_label: str) -> Optional[str]:
    """Extract the root position from a starter label like 'QB1' -> 'QB'."""
    if position_label is None:
        return None
    if position_label == "FLEX":
        return "FLEX"
    # strip trailing digits
    i = len(position_label)
    while i > 0 and position_label[i - 1].isdigit():
        i -= 1
    return position_label[:i]


def position_compatible(player_position: str, position_label: str) -> bool:
    """Check whether a Player.position can fill a starter slot label."""
    if position_label is None:
        return True
    if position_label == "FLEX":
        return player_position in FLEX_POSITIONS
    root = position_root(position_label)
    if root in {"QB", "RB", "WR", "TE", "K", "DST"}:
        return player_position == root or (
            player_position == "FLEX_RWT" and root in {"RB", "WR", "TE"}
        )
    return False


def patch_roster_slot(team_id: str, slot_id: str, body: Dict[str, Any], acting_user_id: str) -> Dict[str, Any]:
    from services.team_service import get_team

    team = get_team(team_id)
    slot = get_slot(slot_id)
    if slot["team_id"] != team_id:
        raise err_resource_not_found(
            f"RosterSlot {slot_id} not in team {team_id}."
        )
    # Ownership
    if team["manager_user_id"] != acting_user_id:
        raise err_not_team_owner()

    # Lineup lock check
    league = store.leagues.get(team["league_id"])
    if league is None:
        raise err_resource_not_found("League not found.")

    # Find current week matchup for this team
    current_week = league.get("current_week", 0)
    if current_week > 0:
        for m in store.matchups_in_league(team["league_id"]):
            if m["week_number"] == current_week and m["status"] == "LOCKED":
                if team_id in (m["home_team_id"], m["away_team_id"]):
                    raise err_lineup_locked()

    new_slot_type = body.get("slot_type", slot["slot_type"])
    new_position_label = body.get("position_label", slot["position_label"])
    version = body.get("version")

    # OCC: version check (only when provided)
    if version is not None:
        if not isinstance(version, int) or isinstance(version, bool):
            raise err_validation("version must be an integer.")
        if version != slot.get("version", 0):
            raise err_version_conflict()

    if new_slot_type not in VALID_SLOT_TYPES:
        raise err_validation(f"slot_type must be in {sorted(VALID_SLOT_TYPES)}.")

    # IR eligibility
    if new_slot_type == "IR":
        player = store.players.get(slot["player_id"])
        if player and player["status_tag"] not in {"OUT", "IR_ELIGIBLE"}:
            raise err_ir_ineligible()

    # Position eligibility
    if new_slot_type == "STARTER":
        if not new_position_label:
            raise err_validation("position_label required for STARTER slot.")
        player = store.players.get(slot["player_id"])
        if player and not position_compatible(player["position"], new_position_label):
            raise err_position_ineligible()
    elif new_slot_type in {"BENCH", "IR"}:
        # position_label should be null for BENCH/IR
        new_position_label = None

    # Apply tentative changes for shape validation
    old_slot_type = slot["slot_type"]
    old_label = slot["position_label"]
    slot["slot_type"] = new_slot_type
    slot["position_label"] = new_position_label

    # Roster shape validation
    try:
        validate_roster_shape(team, league)
        if new_slot_type == "STARTER":
            validate_starter_positions(team, league)
    except Exception:
        # Rollback
        slot["slot_type"] = old_slot_type
        slot["position_label"] = old_label
        raise

    stamp_update(slot)
    return slot


def validate_roster_shape(team: Dict[str, Any], league: Dict[str, Any]) -> None:
    slots = store.roster_slots_for_team(team["id"])
    starters = [s for s in slots if s["slot_type"] == "STARTER"]
    bench = [s for s in slots if s["slot_type"] == "BENCH"]
    ir = [s for s in slots if s["slot_type"] == "IR"]

    if len(starters) != league["starter_count"]:
        raise err_roster_shape_invalid(
            f"Starter count {len(starters)} != required {league['starter_count']}."
        )
    bench_cap = league["roster_size"] - league["starter_count"] - league["ir_slots"]
    if len(bench) > bench_cap:
        raise err_roster_shape_invalid(
            f"Bench size {len(bench)} > cap {bench_cap}."
        )
    if len(ir) > league["ir_slots"]:
        raise err_roster_shape_invalid(
            f"IR size {len(ir)} > cap {league['ir_slots']}."
        )


def validate_starter_positions(team: Dict[str, Any], league: Dict[str, Any]) -> None:
    """Enforce per-position starter slot counts.

    For the default 10-starter setup:
      exactly 1 QB, 2 RB, 3 WR, 1 TE, 1 FLEX, 1 K, 1 DST.
    For any other starter_count we simply require that each unique label has
    exactly one starter (i.e., no duplicates on label).
    """
    slots = store.roster_slots_for_team(team["id"])
    starters = [s for s in slots if s["slot_type"] == "STARTER"]
    labels = [s["position_label"] for s in starters]
    if len(set(labels)) != len(labels):
        raise err_position_constraint("Starter labels must be unique.")

    if league["starter_count"] == 10:
        required = {"QB1", "RB1", "RB2", "WR1", "WR2", "WR3", "TE1", "FLEX", "K1", "DST1"}
        if set(labels) != required:
            raise err_position_constraint(
                f"Starter labels must equal {sorted(required)}."
            )


def list_slots_for_team(team_id: str) -> List[Dict[str, Any]]:
    items = store.roster_slots_for_team(team_id)
    items.sort(key=lambda x: x["created_at"])
    return items
