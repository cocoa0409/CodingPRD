"""Stores, stock positions, delivery trucks and the logical clock."""
from flask import Blueprint, request

import clock
import db
import response
import validate as v
from errors import ApiError
from middleware import auth

bp = Blueprint("config", __name__)

ACCESS_TYPES = ("CURBSIDE", "DRIVEWAY", "NARROW_ALLEY", "CRANE_REQUIRED")

READ_STORE_ROLES = ("PlatformAdmin", "StoreOperations", "ProDeskAssociate",
                    "CreditManager", "ContractorAdmin")
READ_STOCK_ROLES = ("PlatformAdmin", "StoreOperations", "ProDeskAssociate")
READ_TRUCK_ROLES = ("StoreOperations", "ProDeskAssociate")


# --------------------------------------------------------------------- stores
@bp.post("/pro/stores")
def create_store():
    auth("PlatformAdmin")
    data = v.body()
    rec = db.new_record("stores", {
        "store_code": v.req_str(data, "store_code"),
        "region_code": v.req_str(data, "region_code"),
        "state_code": v.req_str(data, "state_code"),
        "distance_rank": v.req_int(data, "distance_rank", minimum=0),
        "will_call_bay_slots": v.req_int(data, "will_call_bay_slots", minimum=1),
        "lift_gate_available": v.req_bool(data, "lift_gate_available"),
        "tax_rate_pct": v.req_number(data, "tax_rate_pct", minimum=0, maximum=0.20),
        "max_stage_hours": v.opt_int(data, "max_stage_hours", default=72, minimum=1),
    })
    return response.obj(db.public(rec), 201)


@bp.get("/pro/stores/<store_id>")
def get_store(store_id):
    auth(*READ_STORE_ROLES)
    return response.obj(db.public(db.require("stores", store_id)))


@bp.get("/pro/stores")
def list_stores():
    auth(*READ_STORE_ROLES)
    records = db.all_of("stores")
    region_code = request.args.get("region_code")
    if region_code is not None:
        records = [r for r in records if r["region_code"] == region_code]
    items, meta = v.paginate(records)
    return response.array(items, 200, meta)


# --------------------------------------------------------------- store stocks
@bp.post("/pro/store-stocks")
def create_store_stock():
    auth("PlatformAdmin")
    data = v.body()
    store = v.resolve_fk(data, "store_id", "stores", "ERR_STORE_NOT_FOUND")
    if store is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field 'store_id' is required.")
    sku = v.req_str(data, "sku")
    on_hand = v.req_int(data, "on_hand_units", minimum=0)
    list_price = v.req_int(data, "list_unit_price_cents", minimum=1)
    for existing in db.all_of("store_stocks"):
        if existing["store_id"] == store["id"] and existing["sku"] == sku:
            raise ApiError("ERR_DUPLICATE_STORE_STOCK", 409)
    rec = db.new_record("store_stocks", {
        "store_id": store["id"],
        "sku": sku,
        "on_hand_units": on_hand,
        "reserved_units": 0,
        "available_units": on_hand,
        "list_unit_price_cents": list_price,
    })
    return response.obj(db.public(rec), 201)


@bp.get("/pro/store-stocks/<store_stock_id>")
def get_store_stock(store_stock_id):
    auth(*READ_STOCK_ROLES)
    return response.obj(db.public(db.require("store_stocks", store_stock_id)))


@bp.get("/pro/store-stocks")
def list_store_stocks():
    auth(*READ_STOCK_ROLES)
    records = db.all_of("store_stocks")
    store_id = request.args.get("store_id")
    if store_id is not None:
        records = [r for r in records if r["store_id"] == store_id]
    sku = request.args.get("sku")
    if sku is not None:
        records = [r for r in records if r["sku"] == sku]
    items, meta = v.paginate(records)
    return response.array(items, 200, meta)


# ------------------------------------------------------------ delivery trucks
@bp.post("/pro/delivery-trucks")
def create_truck():
    auth("StoreOperations")
    data = v.body()
    store = v.resolve_fk(data, "store_id", "stores", "ERR_STORE_NOT_FOUND")
    if store is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field 'store_id' is required.")
    rec = db.new_record("delivery_trucks", {
        "store_id": store["id"],
        "truck_code": v.req_str(data, "truck_code"),
        "lift_gate_equipped": v.req_bool(data, "lift_gate_equipped"),
        "turnaround_buffer_minutes": v.opt_int(
            data, "turnaround_buffer_minutes", default=30, minimum=0),
        "access_types_supported": v.req_string_array(data, "access_types_supported", ACCESS_TYPES),
        "status": "AVAILABLE",
    })
    return response.obj(db.public(rec), 201)


@bp.get("/pro/delivery-trucks/<delivery_truck_id>")
def get_truck(delivery_truck_id):
    auth(*READ_TRUCK_ROLES)
    return response.obj(db.public(db.require("delivery_trucks", delivery_truck_id)))


@bp.get("/pro/delivery-trucks")
def list_trucks():
    auth(*READ_TRUCK_ROLES)
    records = db.all_of("delivery_trucks")
    store_id = request.args.get("store_id")
    if store_id is not None:
        records = [r for r in records if r["store_id"] == store_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, meta = v.paginate(records)
    return response.array(items, 200, meta)


@bp.post("/pro/delivery-trucks/<delivery_truck_id>/out-of-service")
def truck_out_of_service(delivery_truck_id):
    auth("StoreOperations")
    truck = db.require("delivery_trucks", delivery_truck_id)
    data = v.body()
    v.req_str(data, "reason_code")
    if truck["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", 409)
    truck["status"] = "OUT_OF_SERVICE"
    db.touch(truck)
    return response.obj(db.public(truck))


# ----------------------------------------------------------------- test clock
@bp.post("/pro/_clock/set_current_utc")
def set_clock():
    auth("PlatformAdmin")
    data = v.body()
    moment = v.req_datetime(data, "to_iso8601")
    clock.set_now(moment)
    return response.obj({"current_utc": clock.now_iso()})
