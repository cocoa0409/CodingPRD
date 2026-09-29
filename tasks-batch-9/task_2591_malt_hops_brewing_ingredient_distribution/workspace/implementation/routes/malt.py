"""Malt products, physical lots, analysis sheets and specification matching."""

from flask import Blueprint, request

from calc import spec_match
from db import by_created, db, new_entity, now, set_dt, touch
from errors import ApiError
from middleware import ALL_ROLES, require
from response import array_response, object_response
from serialize import malt_lot_out, malt_product_out, spec_match_out
from util import D
from validation import (
    body,
    f_dec,
    f_dt,
    f_enum,
    f_int,
    f_str,
    filter_exists,
    must_exist,
    paginate,
    pagination,
)

bp = Blueprint("malt", __name__)


@bp.post("/malt-products")
def create_product():
    require(("WarehouseOperator", "PlatformAdmin"))
    payload = body()
    sku = f_str(payload, "sku", min_len=1, max_len=30)
    name = f_str(payload, "name", min_len=1, max_len=80)
    malt_class = f_enum(payload, "malt_class", ("BASE", "SPECIALTY"), required=True)
    list_price = f_dec(
        payload, "list_price_cents_per_lb", required=True, scale=2, exclusive_min=0
    )
    max_moisture = f_dec(
        payload,
        "max_moisture_pct",
        required=False,
        scale=2,
        exclusive_min=0,
        default=D("5.0"),
    )
    min_diastatic = f_dec(
        payload,
        "min_diastatic_power",
        required=False,
        scale=2,
        minimum=0,
        default=D("60.0"),
    )
    pallet_quantity = f_int(
        payload, "pallet_quantity_lbs", required=False, minimum=1, default=2200
    )
    min_order = f_int(payload, "min_order_lbs", required=False, minimum=1, default=55)

    for existing in db.malt_products.values():
        if existing["sku"] == sku:
            raise ApiError("ERR_DUPLICATE_RESOURCE_CODE", "sku is already registered")

    product = new_entity()
    product.update(
        {
            "sku": sku,
            "name": name,
            "malt_class": malt_class,
            "pallet_quantity_lbs": pallet_quantity,
            "min_order_lbs": min_order,
            "list_price_cents_per_lb": list_price,
            "max_moisture_pct": max_moisture,
            "min_diastatic_power": min_diastatic,
            "cold_storage_required": False,
        }
    )
    db.malt_products[product["id"]] = product
    return object_response(malt_product_out(product), 201)


@bp.get("/malt-products/<product_id>")
def get_product(product_id):
    require(ALL_ROLES)
    product = must_exist("malt_products", product_id)
    return object_response(malt_product_out(product))


@bp.post("/malt-lots")
def receive_lot():
    require(("WarehouseOperator",))
    payload = body()
    product_id = f_str(payload, "malt_product_id", min_len=1)
    lot_code = f_str(payload, "lot_code", min_len=1, max_len=40)
    quantity = f_int(payload, "quantity_lbs", required=True, minimum=1)
    received_at, received_raw = f_dt(payload, "received_at", required=False)

    must_exist("malt_products", product_id)
    for existing in db.malt_lots.values():
        if existing["lot_code"] == lot_code:
            raise ApiError("ERR_DUPLICATE_LOT_CODE", "lot_code is already registered")

    lot = new_entity()
    lot.update(
        {
            "malt_product_id": product_id,
            "lot_code": lot_code,
            "quantity_lbs": quantity,
            "color_lovibond": None,
            "extract_pct": None,
            "moisture_pct": None,
            "protein_pct": None,
            "diastatic_power": None,
            "analysis_count": 0,
            "analyzed_by_user_id": None,
            "released_by_user_id": None,
            "quarantine_reason": None,
            "status": "RECEIVED",
        }
    )
    if received_at is None:
        set_dt(lot, "received_at", now())
    else:
        set_dt(lot, "received_at", received_at, received_raw)
    db.malt_lots[lot["id"]] = lot
    return object_response(malt_lot_out(lot), 201)


@bp.get("/malt-lots/<lot_id>")
def get_lot(lot_id):
    require(ALL_ROLES)
    lot = must_exist("malt_lots", lot_id)
    return object_response(malt_lot_out(lot))


@bp.get("/malt-lots")
def list_lots():
    require(ALL_ROLES)
    limit, offset = pagination()
    product_id = request.args.get("malt_product_id")
    status = request.args.get("status")
    filter_exists("malt_products", product_id)

    items = []
    for lot in db.malt_lots.values():
        if product_id and lot["malt_product_id"] != product_id:
            continue
        if status and lot["status"] != status:
            continue
        items.append(lot)
    items = by_created(items)
    page = paginate(items, limit, offset)
    return array_response([malt_lot_out(l) for l in page], len(items), limit, offset)


@bp.post("/malt-lots/<lot_id>/analysis")
def file_analysis(lot_id):
    actor = require(("WarehouseOperator",))
    payload = body()
    color = f_dec(payload, "color_lovibond", required=True, scale=2, minimum=0)
    extract = f_dec(payload, "extract_pct", required=True, scale=2, minimum=0)
    moisture = f_dec(payload, "moisture_pct", required=True, scale=2, minimum=0)
    protein = f_dec(payload, "protein_pct", required=True, scale=2, minimum=0)
    diastatic = f_dec(payload, "diastatic_power", required=True, scale=2, minimum=0)

    lot = must_exist("malt_lots", lot_id)
    if lot["status"] != "RECEIVED":
        raise ApiError(
            "ERR_INVALID_LOT_STATE",
            "An analysis sheet may only be filed against a RECEIVED lot",
        )
    product = db.malt_products[lot["malt_product_id"]]

    lot["color_lovibond"] = color
    lot["extract_pct"] = extract
    lot["moisture_pct"] = moisture
    lot["protein_pct"] = protein
    lot["diastatic_power"] = diastatic
    lot["analysis_count"] = int(lot["analysis_count"]) + 1
    lot["analyzed_by_user_id"] = actor.user_id

    if moisture > D(product["max_moisture_pct"]):
        lot["status"] = "QUARANTINED"
        lot["quarantine_reason"] = "MOISTURE_ABOVE_MAX"
    elif product["malt_class"] == "BASE" and diastatic < D(product["min_diastatic_power"]):
        lot["status"] = "QUARANTINED"
        lot["quarantine_reason"] = "DIASTATIC_POWER_BELOW_MIN"
    else:
        lot["status"] = "PASSED"
        lot["quarantine_reason"] = None
    touch(lot)
    return object_response(malt_lot_out(lot))


@bp.post("/malt-lots/<lot_id>/release")
def release_lot(lot_id):
    actor = require(("WarehouseOperator",))
    payload = body()
    f_str(payload, "release_note", required=False, max_len=1000)

    lot = must_exist("malt_lots", lot_id)
    if lot["status"] != "PASSED":
        raise ApiError("ERR_INVALID_LOT_STATE", "Only a PASSED lot may be released")
    if actor.user_id == lot["analyzed_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The user who filed the analysis sheet may not release the lot",
        )
    lot["status"] = "RELEASED"
    lot["released_by_user_id"] = actor.user_id
    touch(lot)
    return object_response(malt_lot_out(lot))


@bp.post("/malt-lots/<lot_id>/retest")
def retest_lot(lot_id):
    require(("WarehouseOperator",))
    payload = body()
    f_str(payload, "retest_reason", required=False, max_len=1000)

    lot = must_exist("malt_lots", lot_id)
    if lot["status"] != "QUARANTINED":
        raise ApiError("ERR_INVALID_LOT_STATE", "Only a QUARANTINED lot may be retested")
    lot["status"] = "RECEIVED"
    lot["quarantine_reason"] = None
    touch(lot)
    return object_response(malt_lot_out(lot))


@bp.post("/malt-lots/<lot_id>/reject")
def reject_lot(lot_id):
    require(("WarehouseOperator",))
    payload = body()
    f_str(payload, "reject_reason", required=True, min_len=1, max_len=1000)

    lot = must_exist("malt_lots", lot_id)
    if lot["status"] != "QUARANTINED":
        raise ApiError("ERR_INVALID_LOT_STATE", "Only a QUARANTINED lot may be rejected")
    lot["status"] = "REJECTED"
    touch(lot)
    return object_response(malt_lot_out(lot))


@bp.get("/malt-lots/<lot_id>/spec-match")
def match_lot(lot_id):
    require(("Brewer", "AllocationManager", "WarehouseOperator", "PlatformAdmin"))
    lot = must_exist("malt_lots", lot_id)
    recipe_id = request.args.get("recipe_id")
    if recipe_id is None:
        payload = body()
        recipe_id = f_str(payload, "recipe_id", min_len=1)
    recipe = must_exist("recipes", recipe_id)
    return object_response(spec_match_out(spec_match(lot, recipe)))
