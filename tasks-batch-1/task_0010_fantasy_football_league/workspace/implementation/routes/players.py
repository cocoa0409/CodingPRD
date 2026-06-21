"""Player CRUD + injury endpoints."""
from flask import Blueprint, request

from db import store
from errors import err_invalid_request, err_invalid_state
from middleware import require_role
from response import success_array, success_object
from services.common import (
    bump,
    check_player_occ,
    get_player,
    new_common_fields,
    paginate,
    parse_pagination,
    serialize,
    serialize_list,
    sort_by_created_at,
)

bp = Blueprint("players", __name__)

ALLOWED_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}


def _validate_number(body, name, *, minv=None, maxv=None, required=True):
    if name not in body or body[name] is None:
        if required:
            raise err_invalid_request(f"Missing {name}.")
        return None
    v = body[name]
    if isinstance(v, bool):
        raise err_invalid_request(f"{name} must be numeric.")
    if not isinstance(v, (int, float)):
        raise err_invalid_request(f"{name} must be numeric.")
    if minv is not None and v < minv:
        raise err_invalid_request(f"{name} below minimum.")
    if maxv is not None and v > maxv:
        raise err_invalid_request(f"{name} above maximum.")
    return v


# ---------------- POST /players ----------------

@bp.route("/players", methods=["POST"])
def create_player():
    require_role("Commissioner")
    body = request.get_json(silent=True) or {}
    full_name = body.get("full_name")
    if not isinstance(full_name, str) or not full_name.strip():
        raise err_invalid_request("Missing or empty full_name.")
    if len(full_name) > 80:
        raise err_invalid_request("full_name too long.")
    position = body.get("position")
    if position not in ALLOWED_POSITIONS:
        raise err_invalid_request("Invalid position.")
    nfl_team = body.get("nfl_team")
    if not isinstance(nfl_team, str):
        raise err_invalid_request("Missing nfl_team.")
    if nfl_team != "FA" and not (
        2 <= len(nfl_team) <= 3 and nfl_team.isalpha() and nfl_team.isupper()
    ):
        raise err_invalid_request("nfl_team must be 2-3 uppercase letters or FA.")
    projected_points = _validate_number(body, "projected_points", minv=0, maxv=50)
    replacement_value = _validate_number(body, "replacement_value", minv=0, maxv=30)

    s = store()
    common = new_common_fields(s.next_seq())
    player = {
        **common,
        "full_name": full_name,
        "position": position,
        "nfl_team": nfl_team,
        "projected_points": projected_points,
        "replacement_value": replacement_value,
        "status": "ACTIVE",
        "current_team_id": None,
    }
    s.players[player["id"]] = player
    return success_object(serialize(player), code=201)


# ---------------- GET /players/{id} ----------------

@bp.route("/players/<pid>", methods=["GET"])
def get_player_endpoint(pid):
    require_role("Commissioner", "TeamOwner")
    player = get_player(pid)
    return success_object(serialize(player))


# ---------------- GET /players ----------------

@bp.route("/players", methods=["GET"])
def list_players():
    require_role("Commissioner", "TeamOwner")
    limit, offset = parse_pagination()
    items = list(store().players.values())
    current_team_id = request.args.get("current_team_id")
    status = request.args.get("status")
    position = request.args.get("position")
    if current_team_id is not None:
        items = [p for p in items if p.get("current_team_id") == current_team_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if position is not None:
        items = [p for p in items if p["position"] == position]
    items = sort_by_created_at(items)
    sliced, total = paginate(items, limit, offset)
    return success_array(serialize_list(sliced), limit, offset, total)


# ---------------- POST /players/{id}/report-injury ----------------

@bp.route("/players/<pid>/report-injury", methods=["POST"])
def report_injury(pid):
    require_role("Commissioner")
    player = get_player(pid)
    body = request.get_json(silent=True) or {}
    if player["status"] != "ACTIVE":
        raise err_invalid_state("Player not ACTIVE.")
    check_player_occ(player, body)
    player["status"] = "INJURED"
    bump(player)
    return success_object(serialize(player))


# ---------------- POST /players/{id}/clear-injury ----------------

@bp.route("/players/<pid>/clear-injury", methods=["POST"])
def clear_injury(pid):
    require_role("Commissioner")
    player = get_player(pid)
    body = request.get_json(silent=True) or {}
    if player["status"] != "INJURED":
        raise err_invalid_state("Player not INJURED.")
    check_player_occ(player, body)
    player["status"] = "ACTIVE"
    bump(player)
    return success_object(serialize(player))
