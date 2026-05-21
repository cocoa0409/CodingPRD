"""Player catalog operations."""
from __future__ import annotations

from typing import Any, Dict, List

from core.errors import err_resource_not_found, err_validation
from core.store import store
from core.utils import is_number
from services.timestamps import stamp_create, stamp_update


VALID_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DST", "FLEX_RWT"}
VALID_STATUS_TAGS = {"ACTIVE", "QUESTIONABLE", "OUT", "IR_ELIGIBLE"}


def create_player(body: Dict[str, Any]) -> Dict[str, Any]:
    full_name = body.get("full_name")
    if not isinstance(full_name, str) or not full_name:
        raise err_validation("full_name required.")
    nfl_team = body.get("nfl_team")
    if not isinstance(nfl_team, str) or not nfl_team:
        raise err_validation("nfl_team required.")
    position = body.get("position")
    if position not in VALID_POSITIONS:
        raise err_validation(f"position must be in {sorted(VALID_POSITIONS)}.")
    proj = body.get("weekly_proj_points", 0)
    if not is_number(proj):
        raise err_validation("weekly_proj_points must be a number.")

    player = {
        "full_name": full_name,
        "nfl_team": nfl_team,
        "position": position,
        "status_tag": "ACTIVE",
        "weekly_proj_points": proj,
    }
    stamp_create(player)
    store.players[player["id"]] = player
    return player


def get_player(player_id: str) -> Dict[str, Any]:
    p = store.players.get(player_id)
    if not p:
        raise err_resource_not_found(f"Player {player_id} not found.")
    return p


def list_players(position=None, status_tag=None) -> List[Dict[str, Any]]:
    items = list(store.players.values())
    if position is not None:
        if position not in VALID_POSITIONS:
            raise err_validation(f"Invalid position filter: {position}.")
        items = [p for p in items if p["position"] == position]
    if status_tag is not None:
        if status_tag not in VALID_STATUS_TAGS:
            raise err_validation(f"Invalid status_tag filter: {status_tag}.")
        items = [p for p in items if p["status_tag"] == status_tag]
    items.sort(key=lambda x: x["created_at"])
    return items


def update_player_status(player_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    player = get_player(player_id)
    status_tag = body.get("status_tag")
    if status_tag not in VALID_STATUS_TAGS:
        raise err_validation(f"status_tag must be in {sorted(VALID_STATUS_TAGS)}.")
    player["status_tag"] = status_tag
    if "weekly_proj_points" in body:
        proj = body["weekly_proj_points"]
        if not is_number(proj):
            raise err_validation("weekly_proj_points must be a number.")
        player["weekly_proj_points"] = proj
    stamp_update(player)
    return player
