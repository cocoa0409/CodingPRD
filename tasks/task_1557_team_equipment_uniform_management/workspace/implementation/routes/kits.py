"""Kit assignments (PRD §3.4)."""
from flask import Blueprint, request

from db import db, clock, stamp, touch, serialize
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_PLAYER_NOT_FOUND,
    ERR_POOL_NOT_FOUND,
    ERR_KIT_ASSIGNMENT_NOT_FOUND,
    ERR_POOL_CLOSED,
    ERR_POOL_SEASON_MISMATCH,
    ERR_JERSEY_NUMBER_TAKEN,
    ERR_POOL_INSUFFICIENT_STOCK,
    ERR_KIT_NOT_RESERVED,
    ERR_KIT_NOT_ISSUED,
    ERR_PLAYER_NOT_ACTIVE,
)
from middleware import endpoint
from response import success
from routes.common import ALL_ROLES, render_list
from services.pools import reconcile_pool, kit_pool_pairs
from util import is_int

bp = Blueprint("kits", __name__)

KIT_STATUSES = {"RESERVED", "ISSUED", "RETURNED", "RELEASED", "LOST"}


@bp.post("/kit-assignments")
@endpoint("EquipmentManager")
def create_kit(ctx):
    b = ctx.body
    player_id = b.get("player_id")
    season_label = b.get("season_label")
    jersey_number = b.get("jersey_number")
    jersey_pool_id = b.get("jersey_pool_id")
    pants_pool_id = b.get("pants_pool_id")
    if not isinstance(player_id, str) or not player_id:
        raise_err(ERR_INVALID_REQUEST, "player_id is required")
    if not isinstance(season_label, str) or not season_label:
        raise_err(ERR_INVALID_REQUEST, "season_label is required")
    if not is_int(jersey_number) or jersey_number < 0 or jersey_number > 99:
        raise_err(ERR_INVALID_REQUEST, "jersey_number must be an integer in [0, 99]")
    if not isinstance(jersey_pool_id, str) or not jersey_pool_id:
        raise_err(ERR_INVALID_REQUEST, "jersey_pool_id is required")
    if not isinstance(pants_pool_id, str) or not pants_pool_id:
        raise_err(ERR_INVALID_REQUEST, "pants_pool_id is required")
    player = db.players.get(player_id)
    if player is None:
        raise_err(ERR_PLAYER_NOT_FOUND, "player not found")
    jersey_pool = db.pools.get(jersey_pool_id)
    if jersey_pool is None:
        raise_err(ERR_POOL_NOT_FOUND, "jersey pool not found")
    pants_pool = db.pools.get(pants_pool_id)
    if pants_pool is None:
        raise_err(ERR_POOL_NOT_FOUND, "pants pool not found")
    for pool in (jersey_pool, pants_pool):
        if pool["status"] != "ACTIVE":
            raise_err(ERR_POOL_CLOSED, "pool is CLOSED")
    if any(
        k
        for k in db.kits.values()
        if k["season_label"] == season_label
        and k["jersey_number"] == jersey_number
        and k["status"] in ("RESERVED", "ISSUED")
    ):
        raise_err(ERR_JERSEY_NUMBER_TAKEN, "jersey number taken for the season")
    for pool in (jersey_pool, pants_pool):
        if pool["season_label"] != season_label:
            raise_err(ERR_POOL_SEASON_MISMATCH, "pool season does not match kit season")
    if jersey_pool["id"] == pants_pool["id"]:
        if jersey_pool["available_quantity"] < 2:
            raise_err(ERR_POOL_INSUFFICIENT_STOCK, "pool has insufficient available units")
    else:
        for pool in (jersey_pool, pants_pool):
            if pool["available_quantity"] < 1:
                raise_err(ERR_POOL_INSUFFICIENT_STOCK, "pool has insufficient available units")
    kit = stamp(
        {
            "player_id": player_id,
            "season_label": season_label,
            "jersey_number": jersey_number,
            "jersey_pool_id": jersey_pool_id,
            "pants_pool_id": pants_pool_id,
            "status": "RESERVED",
            "issued_at": None,
            "closed_at": None,
        }
    )
    db.kits[kit["id"]] = kit
    for pool, units in kit_pool_pairs(kit):
        prev = pool["available_quantity"]
        pool["reserved_quantity"] += units
        reconcile_pool(pool, "decrease", prev)
    return success(serialize(kit), 201)


@bp.get("/kit-assignments")
@endpoint(*ALL_ROLES)
def list_kits(ctx):
    status = request.args.get("status")
    if status is not None and status not in KIT_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "status filter is not a declared value")
    return render_list(
        db.kits,
        {
            "player_id": request.args.get("player_id"),
            "jersey_pool_id": request.args.get("jersey_pool_id"),
            "pants_pool_id": request.args.get("pants_pool_id"),
            "season_label": request.args.get("season_label"),
            "status": status,
        },
    )


@bp.get("/kit-assignments/<kit_id>")
@endpoint(*ALL_ROLES)
def get_kit(ctx, kit_id):
    kit = db.kits.get(kit_id)
    if kit is None:
        raise_err(ERR_KIT_ASSIGNMENT_NOT_FOUND, "kit assignment not found")
    return success(serialize(kit))


@bp.post("/kit-assignments/<kit_id>/issue")
@endpoint("EquipmentManager")
def issue_kit(ctx, kit_id):
    kit = db.kits.get(kit_id)
    if kit is None:
        raise_err(ERR_KIT_NOT_RESERVED, "kit assignment not found")
    if kit["status"] != "RESERVED":
        raise_err(ERR_KIT_NOT_RESERVED, "issue requires kit in RESERVED")
    player = db.players.get(kit["player_id"])
    if player is None or player["status"] != "ACTIVE":
        raise_err(ERR_PLAYER_NOT_ACTIVE, "player is not ACTIVE")
    for pool, _units in kit_pool_pairs(kit):
        if pool["status"] != "ACTIVE":
            raise_err(ERR_POOL_CLOSED, "pool is CLOSED")
    for pool, units in kit_pool_pairs(kit):
        prev = pool["available_quantity"]
        pool["reserved_quantity"] -= units
        pool["stock_on_hand"] -= units
        reconcile_pool(pool, "decrease", prev)
    kit["status"] = "ISSUED"
    kit["issued_at"] = clock()
    touch(kit)
    return success(serialize(kit))


@bp.post("/kit-assignments/<kit_id>/release")
@endpoint("EquipmentManager")
def release_kit(ctx, kit_id):
    kit = db.kits.get(kit_id)
    if kit is None:
        raise_err(ERR_KIT_NOT_RESERVED, "kit assignment not found")
    if kit["status"] != "RESERVED":
        raise_err(ERR_KIT_NOT_RESERVED, "release requires kit in RESERVED")
    for pool, units in kit_pool_pairs(kit):
        prev = pool["available_quantity"]
        pool["reserved_quantity"] -= units
        reconcile_pool(pool, "increase", prev)
    kit["status"] = "RELEASED"
    kit["closed_at"] = clock()
    touch(kit)
    return success(serialize(kit))


@bp.post("/kit-assignments/<kit_id>/return")
@endpoint("EquipmentManager")
def return_kit(ctx, kit_id):
    kit = db.kits.get(kit_id)
    if kit is None:
        raise_err(ERR_KIT_NOT_ISSUED, "kit assignment not found")
    if kit["status"] != "ISSUED":
        raise_err(ERR_KIT_NOT_ISSUED, "return requires kit in ISSUED")
    for pool, units in kit_pool_pairs(kit):
        prev = pool["available_quantity"]
        pool["stock_on_hand"] += units
        reconcile_pool(pool, "increase", prev)
    kit["status"] = "RETURNED"
    kit["closed_at"] = clock()
    touch(kit)
    return success(serialize(kit))
