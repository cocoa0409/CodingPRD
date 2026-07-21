from flask import Blueprint

import store
from common import (
    authorize, get_json, need, as_str, as_int, as_enum,
    require_found, parse_pagination, paginate,
)
from envelope import object_response, array_response
from errors import err

bp = Blueprint("products", __name__)

KINDS = ("GAME", "CONSOLE", "ACCESSORY")
GRADES = ("A", "B", "C", "D")


@bp.post("/products")
def create_product():
    authorize(["Clerk", "Manager"])
    body = get_json()
    title = as_str(need(body, "title"), "title")
    kind = as_enum(need(body, "kind"), "kind", KINDS)
    base_price = as_int(need(body, "base_price_cents"), "base_price_cents")
    if base_price <= 0:
        raise err("ERR_VALIDATION", "base_price_cents must be > 0")
    base_trade = as_int(need(body, "base_trade_value_cents"), "base_trade_value_cents")
    if base_trade < 0:
        raise err("ERR_VALIDATION", "base_trade_value_cents must be >= 0")
    daily_rate = 0
    if body.get("daily_rental_rate_cents") is not None:
        daily_rate = as_int(body["daily_rental_rate_cents"], "daily_rental_rate_cents")
        if daily_rate < 0:
            raise err("ERR_VALIDATION", "daily_rental_rate_cents must be >= 0")
    p = store.make_record({
        "title": title,
        "kind": kind,
        "base_price_cents": base_price,
        "base_trade_value_cents": base_trade,
        "daily_rental_rate_cents": daily_rate,
    })
    store.products[p["id"]] = p
    return object_response(store.serialize(p), 201)


@bp.get("/products/<pid>")
def get_product(pid):
    authorize(["Member", "Clerk", "Manager"])
    p = require_found(store.products, pid)
    return object_response(store.serialize(p), 200)


@bp.get("/products/<pid>/stocks")
def list_product_stocks(pid):
    authorize(["Member", "Clerk", "Manager"])
    require_found(store.products, pid)
    limit, offset = parse_pagination()
    matching = [s for s in store.product_stocks.values() if s["product_id"] == pid]
    window, total = paginate(matching, limit, offset)
    return array_response([store.serialize(s) for s in window], limit, offset, total)


@bp.get("/products/<pid>/inventory-items")
def list_product_inventory(pid):
    authorize(["Member", "Clerk", "Manager"])
    require_found(store.products, pid)
    limit, offset = parse_pagination()
    matching = [i for i in store.inventory_items.values() if i["product_id"] == pid]
    window, total = paginate(matching, limit, offset)
    return array_response([store.serialize(i) for i in window], limit, offset, total)


@bp.post("/products/<pid>/stocks")
def create_product_stock(pid):
    authorize(["Manager"])
    require_found(store.products, pid)
    body = get_json()
    unit_price = as_int(need(body, "unit_price_cents"), "unit_price_cents")
    if unit_price <= 0:
        raise err("ERR_VALIDATION", "unit_price_cents must be > 0")
    deposit = as_int(need(body, "deposit_cents"), "deposit_cents")
    if deposit <= 0 or deposit > unit_price:
        raise err("ERR_VALIDATION", "deposit_cents must satisfy 0 < deposit <= unit_price")
    total_count = as_int(need(body, "total_count"), "total_count")
    if total_count <= 0:
        raise err("ERR_VALIDATION", "total_count must be > 0")
    s = store.make_record({
        "product_id": pid,
        "unit_price_cents": unit_price,
        "deposit_cents": deposit,
        "total_count": total_count,
        "available_count": total_count,
        "allocated_count": 0,
        "fulfilled_count": 0,
        "release_state": "EMBARGOED",
    })
    store.product_stocks[s["id"]] = s
    return object_response(store.serialize(s), 201)


@bp.post("/products/<pid>/inventory-items")
def create_inventory_item(pid):
    authorize(["Clerk", "Manager"])
    require_found(store.products, pid)
    body = get_json()
    grade = as_enum(need(body, "condition_grade"), "condition_grade", GRADES)
    acq = 0
    if body.get("acquisition_cost_cents") is not None:
        acq = as_int(body["acquisition_cost_cents"], "acquisition_cost_cents")
        if acq < 0:
            raise err("ERR_VALIDATION", "acquisition_cost_cents must be >= 0")
    i = store.make_record({
        "product_id": pid,
        "condition_grade": grade,
        "acquisition_cost_cents": acq,
        "status": "AVAILABLE",
    })
    store.inventory_items[i["id"]] = i
    return object_response(store.serialize(i), 201)
