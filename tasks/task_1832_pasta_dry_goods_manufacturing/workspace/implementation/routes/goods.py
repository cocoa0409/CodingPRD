"""FinishedGoodsLot endpoints: list/get (with lazy EXPIRED sweep), put-away, release."""
from flask import Blueprint

import db
from db import store, touch
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import ok, paginate
from services.cascades import occupied_pallets, sweep_all_goods_lots, sweep_goods_lot
from validation import fk_exists, raw_body, require_path_entity, validate_schema

bp = Blueprint("goods", __name__)


@bp.get("/finished-goods-lots")
def list_goods_lots():
    get_context()
    require_roles(ALL_ROLES)
    sweep_all_goods_lots()  # lazy EXPIRED sweep is read-endpoint-only (PRD §2.5)
    rows = list(store.finished_goods_lots.values())
    for field in ("packaging_job_id", "run_id", "zone_id", "status"):
        rows = paginate.filter(rows, field)
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/finished-goods-lots/<lot_id>")
def get_goods_lot(lot_id):
    get_context()
    require_roles(ALL_ROLES)
    lot = require_path_entity(store.finished_goods_lots, lot_id, "ERR_GOODS_LOT_NOT_FOUND")
    sweep_goods_lot(lot)
    return ok(lot)


@bp.post("/finished-goods-lots/<lot_id>/put-away")
def put_away(lot_id):
    get_context()
    require_roles(["WarehouseClerk"])
    lot = require_path_entity(store.finished_goods_lots, lot_id, "ERR_GOODS_LOT_NOT_FOUND")
    body = raw_body()
    zone = fk_exists(store.warehouse_zones, body, "zone_id", "ERR_ZONE_NOT_FOUND")
    validate_schema(body, {"zone_id": ("string", True, None)})
    if lot["status"] != "CREATED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a CREATED lot can be put away")
    # Zone gates in the pinned order: quarantine -> type segregation -> capacity.
    if zone["pest_posture"] == "QUARANTINED":
        raise ApiError("ERR_ZONE_QUARANTINED", 409, "Zone is QUARANTINED")
    if lot["gluten_free"] and zone["zone_type"] != "GLUTEN_FREE":
        raise ApiError("ERR_ZONE_TYPE_MISMATCH", 409,
                       "Gluten-free lot requires a GLUTEN_FREE zone")
    if occupied_pallets(zone["id"]) + lot["pallet_count"] > zone["capacity_pallets"]:
        raise ApiError("ERR_ZONE_CAPACITY_EXCEEDED", 409,
                       "Put-away would exceed zone pallet capacity")
    lot["status"] = "STORED"
    lot["zone_id"] = zone["id"]
    lot["_occupying"] = True
    touch(lot)
    return ok(lot)


@bp.post("/finished-goods-lots/<lot_id>/release")
def release(lot_id):
    get_context()
    require_roles(["WarehouseClerk"])
    lot = require_path_entity(store.finished_goods_lots, lot_id, "ERR_GOODS_LOT_NOT_FOUND")
    if lot["status"] != "STORED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a STORED lot can be released")
    # Temporal gates (priority 9) before referential (10) before constraint (11).
    today = db.clock_today()
    if lot["expiry_date"] is not None and today > lot["expiry_date"]:
        # Write paths never sweep: a still-STORED lot past expiry fails temporally.
        raise ApiError("ERR_LOT_EXPIRED", 409, "Current date is past expiry_date")
    run = store.production_runs[lot["run_id"]]
    recipe = store.recipes[run["recipe_id"]]
    if lot["brand_type"] == "PRIVATE_LABEL" and lot["expiry_date"] is not None:
        remaining_days = (lot["expiry_date"] - today).days
        fraction = db.dec(remaining_days) / db.dec(recipe["shelf_life_days"])
        if fraction < db.dec(recipe["min_remaining_shelf_life_pct"]):
            raise ApiError("ERR_SHELF_LIFE_INSUFFICIENT", 409,
                           "Remaining shelf-life fraction below the recipe minimum")
    if run["quality_disposition"] != "RELEASED":
        raise ApiError("ERR_RUN_QUALITY_NOT_RELEASED", 409,
                       "Run quality_disposition is not RELEASED")
    zone = store.warehouse_zones.get(lot["zone_id"])
    if zone is not None and zone["pest_posture"] == "QUARANTINED":
        raise ApiError("ERR_ZONE_QUARANTINED", 409, "Zone is QUARANTINED")
    lot["status"] = "RELEASED"
    lot["_occupying"] = False
    touch(lot)
    return ok(lot)
