"""Chain configuration: stores, holding equipment, the menu catalogue,
daypart transitions, inspection readiness and the logical clock."""

from flask import Blueprint

from apihttp import authenticate, created, get_body, listing, ok, paginate, pagination, query_str
from calc import (
    daypart_transition_sweep,
    find_holding_unit,
    find_menu_item,
    find_store,
    inspection_readiness,
)
from core import DAYPARTS, STATIONS, base_record, daypart_for_instant, db, fmt_dt, sort_created, touch
from errors import ApiError
from serialize import holding_unit_out, menu_item_out, modifier_option_out, store_out

bp = Blueprint("config", __name__)

ALL_STAFF = (
    "ChainAdmin", "StoreManager", "KitchenAssociate", "ShiftLead",
    "FoodSafetyLead", "StoreTerminal",
)
UNIT_TYPES = ("HOT_CASE", "COLD_CASE", "BAKERY_CASE")
UNIT_STATUSES = ("OPERATIONAL", "IMPAIRED", "LOCKED_OUT")
FULFILLMENT_MODES = ("MADE_TO_ORDER", "PAR_BAKED_CASE")
MODIFIER_CLASSES = ("BREAD", "PROTEIN", "CHEESE", "TOPPING", "PREP", "SIZE")


@bp.post("/stores")
def create_store():
    authenticate(("ChainAdmin",))
    body = get_body()
    store_code = body.string("store_code", min_len=1, max_len=16)
    name = body.string("name", min_len=1)
    hot_case_slot_capacity = body.integer("hot_case_slot_capacity", minimum=1)
    pickup_slot_capacity = body.integer("pickup_slot_capacity", minimum=1)
    is_fuel_site = body.boolean("is_fuel_site", required=False, default=True)
    for existing in db.stores.values():
        if existing["store_code"] == store_code:
            raise ApiError("ERR_DUPLICATE_CODE")
    rec = base_record()
    rec.update({
        "store_code": store_code,
        "name": name,
        "is_fuel_site": is_fuel_site,
        "current_daypart": "BREAKFAST",
        "daypart_epoch": 0,
        "hot_case_slot_capacity": hot_case_slot_capacity,
        "hot_case_slots_used": 0,
        "pickup_slot_capacity": pickup_slot_capacity,
        "waste_cost_cents_mtd": 0,
        "rework_waste_cents_mtd": 0,
    })
    db.stores[rec["id"]] = rec
    return created(store_out(rec))


@bp.get("/stores/<store_id>")
def read_store(store_id):
    authenticate(ALL_STAFF)
    return ok(store_out(find_store(store_id)))


@bp.post("/stores/<store_id>/holding-units")
def create_holding_unit(store_id):
    authenticate(("ChainAdmin", "StoreManager"))
    body = get_body()
    unit_code = body.string("unit_code", min_len=1)
    unit_type = body.enum("unit_type", UNIT_TYPES)
    min_temp_f = body.number("min_temp_f")
    max_temp_f = body.number("max_temp_f")
    slot_count = body.integer("slot_count", minimum=1)
    if max_temp_f <= min_temp_f:
        raise ApiError("ERR_INVALID_REQUEST", "max_temp_f must be greater than min_temp_f.")
    store = find_store(store_id)
    for existing in db.holding_units.values():
        if existing["store_id"] == store["id"] and existing["unit_code"] == unit_code:
            raise ApiError("ERR_DUPLICATE_CODE")
    rec = base_record()
    rec.update({
        "store_id": store["id"],
        "unit_code": unit_code,
        "unit_type": unit_type,
        "min_temp_f": min_temp_f,
        "max_temp_f": max_temp_f,
        "slot_count": slot_count,
        "status": "OPERATIONAL",
        "consecutive_out_of_range_count": 0,
        "last_temp_log_at": None,
    })
    db.holding_units[rec["id"]] = rec
    return created(holding_unit_out(rec))


@bp.get("/stores/<store_id>/holding-units")
def list_holding_units(store_id):
    authenticate(("ChainAdmin", "StoreManager", "KitchenAssociate", "ShiftLead", "FoodSafetyLead"))
    store = find_store(store_id)
    status = query_str("status")
    units = [u for u in db.holding_units.values() if u["store_id"] == store["id"]]
    if status is not None:
        units = [u for u in units if u["status"] == status]
    return paginate(sort_created(units), holding_unit_out)


@bp.get("/holding-units/<unit_id>")
def read_holding_unit(unit_id):
    authenticate(("ChainAdmin", "StoreManager", "KitchenAssociate", "ShiftLead", "FoodSafetyLead"))
    return ok(holding_unit_out(find_holding_unit(unit_id)))


@bp.post("/menu-items")
def create_menu_item():
    authenticate(("ChainAdmin",))
    body = get_body()
    sku = body.string("sku", min_len=1)
    name = body.string("name", min_len=1)
    station = body.enum("station", STATIONS)
    fulfillment_mode = body.enum("fulfillment_mode", FULFILLMENT_MODES)
    base_price_cents = body.integer("base_price_cents", minimum=0)
    unit_food_cost_cents = body.integer("unit_food_cost_cents", minimum=0)
    valid_dayparts = body.enum_array("valid_dayparts", DAYPARTS)
    prep_seconds = body.integer("prep_seconds", required=False, default=0, minimum=0)
    bake_minutes = body.integer("bake_minutes", required=False, default=0, minimum=0)
    hold_minutes = body.integer("hold_minutes", required=False, default=0, minimum=0)
    included_premium_count = body.integer(
        "included_premium_count", required=False, default=0, minimum=0
    )
    is_catering_eligible = body.boolean("is_catering_eligible", required=False, default=False)
    if unit_food_cost_cents > base_price_cents:
        raise ApiError(
            "ERR_INVALID_REQUEST", "unit_food_cost_cents must not exceed base_price_cents."
        )
    for existing in db.menu_items.values():
        if existing["sku"] == sku:
            raise ApiError("ERR_DUPLICATE_CODE")
    rec = base_record()
    rec.update({
        "sku": sku,
        "name": name,
        "station": station,
        "fulfillment_mode": fulfillment_mode,
        "base_price_cents": base_price_cents,
        "unit_food_cost_cents": unit_food_cost_cents,
        "prep_seconds": prep_seconds,
        "bake_minutes": bake_minutes,
        "hold_minutes": hold_minutes,
        "valid_dayparts": valid_dayparts,
        "included_premium_count": included_premium_count,
        "is_catering_eligible": is_catering_eligible,
    })
    db.menu_items[rec["id"]] = rec
    return created(menu_item_out(rec))


@bp.get("/menu-items/<item_id>")
def read_menu_item(item_id):
    authenticate(("ChainAdmin", "StoreManager", "StoreTerminal", "Customer", "KitchenAssociate"))
    return ok(menu_item_out(find_menu_item(item_id)))


@bp.post("/menu-items/<item_id>/modifier-options")
def create_modifier_option(item_id):
    authenticate(("ChainAdmin",))
    body = get_body()
    code = body.string("code", min_len=1)
    modifier_class = body.enum("modifier_class", MODIFIER_CLASSES)
    price_delta_cents = body.integer("price_delta_cents", minimum=0)
    is_premium = body.boolean("is_premium", required=False, default=False)
    max_qty = body.integer("max_qty", required=False, default=1, minimum=1)
    item = find_menu_item(item_id)
    for existing in db.modifier_options.values():
        if existing["menu_item_id"] == item["id"] and existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE")
    rec = base_record(versioned=False)
    rec.update({
        "menu_item_id": item["id"],
        "code": code,
        "modifier_class": modifier_class,
        "price_delta_cents": price_delta_cents,
        "is_premium": is_premium,
        "max_qty": max_qty,
    })
    db.modifier_options[rec["id"]] = rec
    return created(modifier_option_out(rec))


@bp.get("/menu-items/<item_id>/modifier-options")
def list_modifier_options(item_id):
    authenticate(("ChainAdmin", "StoreTerminal", "Customer", "KitchenAssociate"))
    item = find_menu_item(item_id)
    modifier_class = query_str("modifier_class")
    options = [o for o in db.modifier_options.values() if o["menu_item_id"] == item["id"]]
    if modifier_class is not None:
        options = [o for o in options if o["modifier_class"] == modifier_class]
    return paginate(sort_created(options), modifier_option_out)


@bp.post("/stores/<store_id>/daypart-transitions")
def daypart_transition(store_id):
    authenticate(("StoreManager",))
    body = get_body()
    to_daypart = body.enum("to_daypart", DAYPARTS)
    store = find_store(store_id)
    due = daypart_for_instant(db.clock)
    if to_daypart != due or to_daypart == store["current_daypart"]:
        raise ApiError("ERR_DAYPART_NOT_DUE")
    store["current_daypart"] = to_daypart
    store["daypart_epoch"] += 1
    touch(store)
    daypart_transition_sweep(store)
    return ok(store_out(store))


@bp.get("/stores/<store_id>/readiness")
def store_readiness(store_id):
    authenticate(("StoreManager", "FoodSafetyLead", "ChainAdmin"))
    store = find_store(store_id)
    return ok(inspection_readiness(store))


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("ChainAdmin",))
    body = get_body()
    instant = body.datetime("to_iso8601")
    if instant <= db.clock:
        raise ApiError("ERR_CLOCK_REGRESSION")
    db.clock = instant
    return ok({"current_utc": fmt_dt(db.clock)})
