"""Team CRUD + lifecycle endpoints."""
from flask import Blueprint, g, request

from db import store
from errors import (
    ERR_INVALID_STARTER_PLAYER,
    APIError,
    err_cross_state,
    err_forbidden,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
    err_roster_cap,
)
from middleware import require_role, require_team_owner_self
from response import success_array, success_object
from services.calculations import recompute_keeper_costs
from services.common import (
    bump,
    check_team_occ,
    get_league,
    get_player,
    get_team,
    new_common_fields,
    paginate,
    parse_pagination,
    serialize,
    serialize_list,
    sort_by_created_at,
)
from services.roster import (
    create_roster_slot,
    delete_roster_slots_for,
    find_player_slot,
    get_ir_count,
    get_non_ir_count,
    get_roster_slots_for_team,
)

bp = Blueprint("teams", __name__)


# ---------------- POST /leagues/{id}/teams ----------------

@bp.route("/leagues/<lid>/teams", methods=["POST"])
def create_team(lid):
    require_role("Commissioner")
    league = get_league(lid)
    if league["status"] != "SETUP":
        raise err_invalid_state("League must be in SETUP to add teams.")

    body = request.get_json(silent=True) or {}
    display_name = body.get("display_name")
    division = body.get("division")
    if not isinstance(display_name, str) or not display_name.strip():
        raise err_invalid_request("Missing or empty display_name.")
    if len(display_name) > 40:
        raise err_invalid_request("display_name too long.")
    if not isinstance(division, str) or not division.strip():
        raise err_invalid_request("Missing or empty division.")
    if len(division) > 20:
        raise err_invalid_request("division too long.")

    # Unique display_name within league (case-insensitive).
    norm = display_name.strip().lower()
    for t in store().teams.values():
        if t["league_id"] == lid and t["display_name"].strip().lower() == norm:
            raise err_invalid_request("display_name not unique within league.")

    s = store()
    common = new_common_fields(s.next_seq())
    team = {
        **common,
        "league_id": lid,
        "display_name": display_name,
        "division": division,
        "faab_balance_cents": 0,
        "waiver_priority": 0,
        "wins": 0,
        "losses": 0,
        "total_points_for": 0,
        "total_points_against": 0,
        "intra_division_wins": 0,
        "playoff_seed": 0,
        "keeper_player_ids": [],
    }
    s.teams[team["id"]] = team
    bump(league)
    return success_object(serialize(team), code=201)


# ---------------- GET /teams/{id} ----------------

@bp.route("/teams/<tid>", methods=["GET"])
def get_team_endpoint(tid):
    require_role("Commissioner", "TeamOwner")
    team = get_team(tid)
    return success_object(serialize(team))


# ---------------- GET /teams ----------------

@bp.route("/teams", methods=["GET"])
def list_teams():
    require_role("Commissioner", "TeamOwner")
    limit, offset = parse_pagination()
    items = list(store().teams.values())
    league_id = request.args.get("league_id")
    if league_id is not None:
        items = [t for t in items if t["league_id"] == league_id]
    items = sort_by_created_at(items)
    sliced, total = paginate(items, limit, offset)
    return success_array(serialize_list(sliced), limit, offset, total)


# ---------------- PATCH /teams/{id}/keepers ----------------

@bp.route("/teams/<tid>/keepers", methods=["PATCH"])
def update_keepers(tid):
    require_role("TeamOwner")
    require_team_owner_self(tid)
    team = get_team(tid)
    body = request.get_json(silent=True) or {}
    keeper_player_ids = body.get("keeper_player_ids")
    if not isinstance(keeper_player_ids, list):
        raise err_invalid_request("keeper_player_ids must be an array.")
    league = get_league(team["league_id"])
    # Existence first.
    for pid in keeper_player_ids:
        if not isinstance(pid, str) or pid not in store().players:
            raise err_not_found(f"Player {pid} not found.")
    check_team_occ(team, body)
    # Keeper-limit + must-be-on-roster check.
    if len(keeper_player_ids) > int(league["keeper_limit"]):
        from errors import ERR_KEEPER_OVER_LIMIT, APIError
        raise APIError(ERR_KEEPER_OVER_LIMIT, 422, "Too many keepers.")
    for pid in keeper_player_ids:
        if find_player_slot(tid, pid) is None:
            from errors import ERR_KEEPER_OVER_LIMIT, APIError
            raise APIError(ERR_KEEPER_OVER_LIMIT, 422,
                           "Keeper not on team's roster.")
    team["keeper_player_ids"] = list(keeper_player_ids)
    recompute_keeper_costs(team)
    bump(team)
    return success_object(serialize(team))


# ---------------- POST /teams/{team_id}/set-lineup ----------------

@bp.route("/teams/<tid>/set-lineup", methods=["POST"])
def set_lineup(tid):
    require_role("TeamOwner")
    require_team_owner_self(tid)
    team = get_team(tid)
    body = request.get_json(silent=True) or {}
    starter_player_ids = body.get("starter_player_ids")
    if not isinstance(starter_player_ids, list):
        raise err_invalid_request("starter_player_ids must be an array.")

    # Existence (body-FK).
    for pid in starter_player_ids:
        if not isinstance(pid, str) or pid not in store().players:
            raise err_not_found(f"Player {pid} not found.")
    check_team_occ(team, body)

    # Safety check: each must be on roster and not IR_PLACED.
    for pid in starter_player_ids:
        slot = find_player_slot(tid, pid)
        if slot is None:
            raise APIError(ERR_INVALID_STARTER_PLAYER, 422,
                           "Player not on roster.")
        player = store().players[pid]
        if player["status"] == "IR_PLACED":
            raise APIError(ERR_INVALID_STARTER_PLAYER, 422,
                           "Player is IR_PLACED.")

    # Apply: starters STARTER, every other non-IR slot BENCH.
    starter_set = set(starter_player_ids)
    for slot in get_roster_slots_for_team(tid):
        if slot["slot_type"] == "IR":
            continue
        slot["slot_type"] = "STARTER" if slot["player_id"] in starter_set else "BENCH"
        bump(slot)
    bump(team)
    return success_object(serialize(team))


# ---------------- POST /teams/{team_id}/place-on-ir ----------------

@bp.route("/teams/<tid>/place-on-ir", methods=["POST"])
def place_on_ir(tid):
    require_role("TeamOwner")
    require_team_owner_self(tid)
    team = get_team(tid)
    body = request.get_json(silent=True) or {}
    player_id = body.get("player_id")
    if not isinstance(player_id, str):
        raise err_invalid_request("player_id required.")
    player = get_player(player_id)
    check_team_occ(team, body)

    if player["status"] != "INJURED":
        raise err_invalid_state("Player not INJURED.")
    if player.get("current_team_id") != tid:
        raise err_invalid_state("Player not on this team.")
    league = get_league(team["league_id"])
    if get_ir_count(tid) >= int(league["ir_slot_count"]):
        raise err_invalid_state("No free IR slots.")

    slot = find_player_slot(tid, player_id)
    if slot is None:
        raise err_invalid_state("Player has no roster slot.")
    slot["slot_type"] = "IR"
    bump(slot)
    player["status"] = "IR_PLACED"
    bump(player)
    bump(team)
    return success_object(serialize(player))


# ---------------- POST /teams/{team_id}/activate-from-ir ----------------

@bp.route("/teams/<tid>/activate-from-ir", methods=["POST"])
def activate_from_ir(tid):
    require_role("TeamOwner")
    require_team_owner_self(tid)
    team = get_team(tid)
    body = request.get_json(silent=True) or {}
    player_id = body.get("player_id")
    if not isinstance(player_id, str):
        raise err_invalid_request("player_id required.")
    player = get_player(player_id)
    check_team_occ(team, body)

    if player["status"] != "IR_PLACED":
        raise err_invalid_state("Player not IR_PLACED.")
    if player.get("current_team_id") != tid:
        raise err_invalid_state("Player not on this team.")
    league = get_league(team["league_id"])
    if (get_non_ir_count(tid) + 1) > int(league["roster_size"]):
        raise err_roster_cap("Roster would exceed roster_size after activation.")
    slot = find_player_slot(tid, player_id)
    if slot is None:
        raise err_invalid_state("Player has no roster slot.")
    slot["slot_type"] = "BENCH"
    bump(slot)
    player["status"] = "ACTIVE"
    bump(player)
    bump(team)
    return success_object(serialize(player))


# ---------------- POST /teams/{team_id}/release-player ----------------

@bp.route("/teams/<tid>/release-player", methods=["POST"])
def release_player(tid):
    require_role("TeamOwner")
    require_team_owner_self(tid)
    team = get_team(tid)
    body = request.get_json(silent=True) or {}
    player_id = body.get("player_id")
    if not isinstance(player_id, str):
        raise err_invalid_request("player_id required.")
    player = get_player(player_id)
    check_team_occ(team, body)

    if player.get("current_team_id") != tid:
        raise err_invalid_state("Player not on this team.")
    if player["status"] != "ACTIVE":
        raise err_invalid_state("Player not ACTIVE.")

    delete_roster_slots_for(tid, player_id)
    player["current_team_id"] = None
    # PRD: pass through RELEASED then immediately back to ACTIVE with
    # current_team_id=null. Net status remains ACTIVE.
    player["status"] = "ACTIVE"
    bump(player)
    bump(team)
    return success_object(serialize(player))


# ---------------- GET /teams/{id}/roster-slots ----------------

@bp.route("/teams/<tid>/roster-slots", methods=["GET"])
def list_team_roster_slots(tid):
    require_role("Commissioner", "TeamOwner")
    get_team(tid)
    limit, offset = parse_pagination()
    items = [s for s in store().roster_slots.values() if s["team_id"] == tid]
    items = sort_by_created_at(items)
    sliced, total = paginate(items, limit, offset)
    return success_array(serialize_list(sliced), limit, offset, total)
