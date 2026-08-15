"""InventoryLot: freeze (shelf-life reset) and spoilage write-off."""
from datetime import timedelta

from flask import Blueprint

from db import store, touch, now
from errors import (
    ApiError,
    ERR_LOT_NOT_FOUND,
    ERR_LOT_INVALID_STATE,
    ERR_LOT_ON_HOLD,
    ERR_INSUFFICIENT_LOT_QUANTITY,
    ERR_INVALID_REQUEST,
)
from middleware import auth, require
from response import ok, ok_list
from services.calc import ZERO, q2
from services.cascades import deplete_check
from util import body, req_num, opt_str, apply_filters

bp = Blueprint("lots", __name__)


def _get_lot(rid):
    rec = store.lots.get(rid)
    if rec is None:
        raise ApiError(ERR_LOT_NOT_FOUND, 404, "InventoryLot id does not exist")
    return rec


@bp.get("/inventory-lots")
def list_lots():
    auth()
    page, total, limit, offset = apply_filters(
        list(store.lots.values()),
        ["landing_line_id", "species_id", "lifecycle_status", "hold_status"],
    )
    return ok_list(page, total, limit, offset)


@bp.get("/inventory-lots/<rid>")
def get_lot(rid):
    auth()
    return ok(_get_lot(rid))


@bp.post("/inventory-lots/<rid>/freeze")
def freeze_lot(rid):
    _, role = auth()
    require(role, {"InventoryPlanner"})
    lot = _get_lot(rid)
    # State (priority 6): lifecycle ACTIVE and currently FRESH.
    if lot["lifecycle_status"] != "ACTIVE" or lot["storage_type"] != "FRESH":
        raise ApiError(
            ERR_LOT_INVALID_STATE, 409,
            "Lot is not an ACTIVE FRESH lot",
        )
    # Safety (priority 7): quarantined lots cannot be frozen.
    if lot["hold_status"] == "ON_HOLD":
        raise ApiError(ERR_LOT_ON_HOLD, 409, "Lot is ON_HOLD")
    species = store.species[lot["species_id"]]
    frozen_at = now()
    lot["storage_type"] = "FROZEN"
    lot["frozen_at"] = frozen_at
    lot["expires_at"] = frozen_at + timedelta(days=species["frozen_shelf_life_days"])
    touch(lot)
    return ok(lot)


@bp.post("/inventory-lots/<rid>/write-off")
def write_off_lot(rid):
    _, role = auth()
    require(role, {"InventoryPlanner"})
    b = body()
    qty_kg = req_num(b, "qty_kg")
    if qty_kg <= ZERO:
        raise ApiError(ERR_INVALID_REQUEST, 400, "qty_kg must be > 0")
    opt_str(b, "reason", "")
    lot = _get_lot(rid)
    if lot["lifecycle_status"] != "ACTIVE":
        raise ApiError(ERR_LOT_INVALID_STATE, 409, "Lot lifecycle is not ACTIVE")
    if lot["hold_status"] == "ON_HOLD":
        raise ApiError(ERR_LOT_ON_HOLD, 409, "Lot is ON_HOLD")
    qty = q2(qty_kg)
    if lot["available_weight_kg"] < qty:
        raise ApiError(
            ERR_INSUFFICIENT_LOT_QUANTITY, 409,
            "Write-off quantity exceeds available weight",
        )
    lot["available_weight_kg"] -= qty
    lot["spoiled_weight_kg"] += qty
    deplete_check(lot)
    touch(lot)
    return ok(lot)
