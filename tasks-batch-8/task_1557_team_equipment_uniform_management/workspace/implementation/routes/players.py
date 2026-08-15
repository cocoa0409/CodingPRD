"""Players (PRD §3.1)."""
from flask import Blueprint

from db import db, clock, stamp, touch, serialize
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_PLAYER_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_PLAYER_HAS_ISSUED_KITS,
)
from middleware import endpoint
from response import success
from routes.common import ALL_ROLES
from services.pools import reconcile_pool, kit_pool_pairs

bp = Blueprint("players", __name__)

POSITION_GROUPS = {"OFFENSE", "DEFENSE", "SPECIAL_TEAMS"}
PLAYER_STATUSES = {"ACTIVE", "SUSPENDED", "RELEASED"}
ALLOWED_TRANSITIONS = {
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "RELEASED"),
    ("SUSPENDED", "RELEASED"),
}


@bp.post("/players")
@endpoint("EquipmentManager")
def create_player(ctx):
    b = ctx.body
    full_name = b.get("full_name")
    position_group = b.get("position_group")
    if not isinstance(full_name, str) or not full_name:
        raise_err(ERR_INVALID_REQUEST, "full_name is required")
    if position_group not in POSITION_GROUPS:
        raise_err(ERR_INVALID_REQUEST, "position_group is not a declared value")
    player = stamp(
        {
            "full_name": full_name,
            "position_group": position_group,
            "status": "ACTIVE",
        }
    )
    db.players[player["id"]] = player
    return success(serialize(player), 201)


@bp.get("/players/<player_id>")
@endpoint(*ALL_ROLES)
def get_player(ctx, player_id):
    player = db.players.get(player_id)
    if player is None:
        raise_err(ERR_PLAYER_NOT_FOUND, "player not found")
    return success(serialize(player))


@bp.patch("/players/<player_id>")
@endpoint("EquipmentManager")
def patch_player(ctx, player_id):
    b = ctx.body
    target = b.get("status")
    if target not in PLAYER_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "status is not a declared value")
    player = db.players.get(player_id)
    if player is None:
        raise_err(ERR_PLAYER_NOT_FOUND, "player not found")
    current = player["status"]
    if (current, target) not in ALLOWED_TRANSITIONS:
        raise_err(ERR_INVALID_STATE, f"transition {current} -> {target} not allowed")
    if target == "RELEASED":
        if any(
            k
            for k in db.kits.values()
            if k["player_id"] == player_id and k["status"] == "ISSUED"
        ):
            raise_err(ERR_PLAYER_HAS_ISSUED_KITS, "player holds kits in ISSUED status")
        # Cascade: this player's RESERVED kits -> RELEASED, reservations restored
        # (increase-direction reconciliation may clear reorder_blocked).
        for kit in [
            k
            for k in db.kits.values()
            if k["player_id"] == player_id and k["status"] == "RESERVED"
        ]:
            for pool, units in kit_pool_pairs(kit):
                prev = pool["available_quantity"]
                pool["reserved_quantity"] -= units
                reconcile_pool(pool, "increase", prev)
            kit["status"] = "RELEASED"
            kit["closed_at"] = clock()
            touch(kit)
    player["status"] = target
    touch(player)
    return success(serialize(player))
