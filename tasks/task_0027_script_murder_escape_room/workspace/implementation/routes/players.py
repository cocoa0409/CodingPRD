"""Player routes."""
from flask import Blueprint
from db import store, make_common
from middleware import require_role
from response import success_object
from validators import (
    get_json_body, require_string, require_int, require_enum, optional_enum,
)
from errors import raise_error, ERR_PLAYER_NOT_FOUND, ERR_INSUFFICIENT_PERMISSIONS

players_bp = Blueprint("players", __name__)


GENDERS = ["MALE", "FEMALE", "UNDISCLOSED"]
EXPS = ["NOVICE", "INTERMEDIATE", "VETERAN"]
TIERS = ["STANDARD", "VIP"]


def player_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "display_name": p["display_name"],
        "gender": p["gender"],
        "age": p["age"],
        "experience_level": p["experience_level"],
        "tier": p["tier"],
        "no_show_strikes": p["no_show_strikes"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@players_bp.route("/players", methods=["POST"])
def create_player():
    user_id, role = require_role("Player", "PlatformAdmin")
    body = get_json_body()
    display_name = require_string(body, "display_name", 1, 200)
    gender = require_enum(body, "gender", GENDERS)
    age = require_int(body, "age", 12, 99)
    experience_level = require_enum(body, "experience_level", EXPS)
    tier = optional_enum(body, "tier", TIERS, default="STANDARD")
    p = make_common({
        "display_name": display_name,
        "gender": gender,
        "age": age,
        "experience_level": experience_level,
        "tier": tier,
        "no_show_strikes": 0,
        "status": "ACTIVE",
    })
    # When self-registering as Player, prefer X-User-ID as the id
    if role == "Player":
        # Replace random id with user_id
        p["id"] = user_id
    store.players[p["id"]] = p
    return success_object(player_view(p), 201)


@players_bp.route("/players/<player_id>", methods=["GET"])
def get_player(player_id):
    user_id, role = require_role("Player", "VenueOperator", "PlatformAdmin")
    p = store.players.get(player_id)
    if not p:
        raise_error(ERR_PLAYER_NOT_FOUND, "player not found")
    if role == "Player" and user_id != player_id:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "not own player")
    return success_object(player_view(p))
