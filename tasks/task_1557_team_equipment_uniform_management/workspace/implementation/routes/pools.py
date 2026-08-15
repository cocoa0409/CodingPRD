"""Inventory pools (PRD §3.2)."""
from flask import Blueprint, request

from db import db, stamp, serialize
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_POOL_NOT_FOUND,
    ERR_POOL_ALREADY_EXISTS,
    ERR_POOL_CLOSED,
    ERR_STALE_POOL_VERSION,
    ERR_STOCK_BELOW_COMMITMENTS,
)
from middleware import endpoint
from response import success
from routes.common import ALL_ROLES, render_list
from services.pools import reconcile_pool
from util import is_int

bp = Blueprint("pools", __name__)

GARMENT_TYPES = {"GAME_JERSEY", "GAME_PANTS", "PRACTICE_JERSEY", "PRACTICE_PANTS", "SOCKS"}
POOL_STATUSES = {"ACTIVE", "CLOSED"}


@bp.post("/inventory-pools")
@endpoint("EquipmentManager")
def create_pool(ctx):
    b = ctx.body
    season_label = b.get("season_label")
    garment_type = b.get("garment_type")
    size_code = b.get("size_code")
    stock_on_hand = b.get("stock_on_hand")
    reorder_point = b.get("reorder_point")
    reorder_batch_size = b.get("reorder_batch_size")
    if not isinstance(season_label, str) or not season_label:
        raise_err(ERR_INVALID_REQUEST, "season_label is required")
    if garment_type not in GARMENT_TYPES:
        raise_err(ERR_INVALID_REQUEST, "garment_type is not a declared value")
    if not isinstance(size_code, str) or not size_code:
        raise_err(ERR_INVALID_REQUEST, "size_code is required")
    if not is_int(stock_on_hand) or stock_on_hand < 0:
        raise_err(ERR_INVALID_REQUEST, "stock_on_hand must be an integer >= 0")
    if not is_int(reorder_point) or reorder_point < 0:
        raise_err(ERR_INVALID_REQUEST, "reorder_point must be an integer >= 0")
    if not is_int(reorder_batch_size) or reorder_batch_size <= 0:
        raise_err(ERR_INVALID_REQUEST, "reorder_batch_size must be an integer > 0")
    if any(
        p
        for p in db.pools.values()
        if p["season_label"] == season_label
        and p["garment_type"] == garment_type
        and p["size_code"] == size_code
    ):
        raise_err(ERR_POOL_ALREADY_EXISTS, "pool already exists for season/garment/size")
    pool = stamp(
        {
            "season_label": season_label,
            "garment_type": garment_type,
            "size_code": size_code,
            "stock_on_hand": stock_on_hand,
            "reserved_quantity": 0,
            "in_laundry_quantity": 0,
            "available_quantity": stock_on_hand,
            "reorder_point": reorder_point,
            "reorder_batch_size": reorder_batch_size,
            "reorder_blocked": False,
            "status": "ACTIVE",
        }
    )
    db.pools[pool["id"]] = pool
    return success(serialize(pool), 201)


@bp.get("/inventory-pools")
@endpoint(*ALL_ROLES)
def list_pools(ctx):
    season_label = request.args.get("season_label")
    garment_type = request.args.get("garment_type")
    status = request.args.get("status")
    if garment_type is not None and garment_type not in GARMENT_TYPES:
        raise_err(ERR_INVALID_REQUEST, "garment_type filter is not a declared value")
    if status is not None and status not in POOL_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "status filter is not a declared value")
    return render_list(
        db.pools,
        {"season_label": season_label, "garment_type": garment_type, "status": status},
    )


@bp.get("/inventory-pools/<pool_id>")
@endpoint(*ALL_ROLES)
def get_pool(ctx, pool_id):
    pool = db.pools.get(pool_id)
    if pool is None:
        raise_err(ERR_POOL_NOT_FOUND, "pool not found")
    return success(serialize(pool))


@bp.post("/inventory-pools/<pool_id>/stock-adjustments")
@endpoint("EquipmentManager")
def stock_adjustment(ctx, pool_id):
    b = ctx.body
    new_stock = b.get("new_stock_on_hand")
    expected = b.get("expected_pool_version")
    if not is_int(new_stock) or new_stock < 0:
        raise_err(ERR_INVALID_REQUEST, "new_stock_on_hand must be an integer >= 0")
    if not is_int(expected):
        raise_err(ERR_INVALID_REQUEST, "expected_pool_version must be an integer")
    pool = db.pools.get(pool_id)
    if pool is None:
        raise_err(ERR_POOL_NOT_FOUND, "pool not found")
    if pool["status"] != "ACTIVE":
        raise_err(ERR_POOL_CLOSED, "pool is CLOSED")
    if expected != pool["version"]:
        raise_err(ERR_STALE_POOL_VERSION, "expected_pool_version is stale")
    if new_stock < pool["reserved_quantity"] + pool["in_laundry_quantity"]:
        raise_err(
            ERR_STOCK_BELOW_COMMITMENTS,
            "new_stock_on_hand below reserved + in-laundry units",
        )
    prev_available = pool["available_quantity"]
    pool["stock_on_hand"] = new_stock
    new_available = new_stock - pool["reserved_quantity"] - pool["in_laundry_quantity"]
    direction = "decrease" if new_available < prev_available else "increase"
    reconcile_pool(pool, direction, prev_available)
    return success(serialize(pool))
