"""Product and SKU (band/cup matrix) endpoints (PRD §3.1)."""
from flask import Blueprint

import store
import api as h
import calc
import serialize as s
from errors import ApiError

bp = Blueprint("catalog", __name__)

CATEGORIES = {"EVERYDAY_BRA", "SPORTS_BRA", "MASTECTOMY_BRA", "LINGERIE_SET"}
HYGIENE = {"STANDARD_RETURNABLE", "INTIMATE_NON_RETURNABLE"}
CUP_SIZES = {"AA", "A", "B", "C", "D", "E", "F", "G", "H"}


@bp.post("/boutique/products")
def create_product():
    h.require_role("StoreManager")
    body = h.get_body()
    h.require_fields(body, ["style_name", "brand", "category", "base_price_cents"])
    if not isinstance(body["style_name"], str) or not isinstance(body["brand"], str):
        raise ApiError("ERR_VALIDATION", "style_name and brand must be strings")
    h.check_enum(body["category"], CATEGORIES, "category")
    base = h.require_int(body, "base_price_cents", minimum=0)
    hygiene = body.get("hygiene_class", "STANDARD_RETURNABLE")
    if hygiene is None:
        hygiene = "STANDARD_RETURNABLE"
    h.check_enum(hygiene, HYGIENE, "hygiene_class")
    is_active = body.get("is_active", True)
    if not isinstance(is_active, bool):
        raise ApiError("ERR_VALIDATION", "is_active must be boolean")
    rec = store.new_record({
        "style_name": body["style_name"],
        "brand": body["brand"],
        "category": body["category"],
        "base_price_cents": base,
        "hygiene_class": hygiene,
        "is_mastectomy": body["category"] == "MASTECTOMY_BRA",
        "is_active": is_active,
    })
    store.products[rec["id"]] = rec
    return h.success(s.product_out(rec), status=201)


@bp.get("/boutique/products/<pid>")
def get_product(pid):
    h.require_role("Customer", "Fitter", "StoreManager", "BillingClerk")
    rec = h.lookup("products", pid)
    return h.success(s.product_out(rec))


@bp.post("/boutique/skus")
def create_sku():
    h.require_role("StoreManager")
    body = h.get_body()
    # existence (priority 3)
    if body.get("product_id") is not None:
        product = h.lookup("products", body["product_id"])
    else:
        product = None
    # validation (priority 5)
    h.require_fields(body, ["product_id", "band_size", "cup_size", "sku_code"])
    band = h.require_int(body, "band_size")
    if band % 2 != 0 or band < 28 or band > 44:
        raise ApiError("ERR_VALIDATION", "band_size must be an even integer in 28..44")
    h.check_enum(body["cup_size"], CUP_SIZES, "cup_size")
    if not isinstance(body["sku_code"], str):
        raise ApiError("ERR_VALIDATION", "sku_code must be a string")
    initial_stock = body.get("initial_stock", 0)
    if initial_stock is None:
        initial_stock = 0
    if not isinstance(initial_stock, int) or isinstance(initial_stock, bool) or initial_stock < 0:
        raise ApiError("ERR_VALIDATION", "initial_stock must be a non-negative integer")
    is_active = body.get("is_active", True)
    if not isinstance(is_active, bool):
        raise ApiError("ERR_VALIDATION", "is_active must be boolean")
    rec = store.new_record({
        "product_id": body["product_id"],
        "band_size": band,
        "cup_size": body["cup_size"],
        "sku_code": body["sku_code"],
        "price_cents": calc.sku_price(product["base_price_cents"], band, body["cup_size"]),
        "stock_on_hand": initial_stock,
        "is_active": is_active,
    })
    store.skus[rec["id"]] = rec
    return h.success(s.sku_out(rec), status=201)


@bp.get("/boutique/skus/<sid>")
def get_sku(sid):
    h.require_role("Customer", "Fitter", "StoreManager", "BillingClerk")
    rec = h.lookup("skus", sid)
    return h.success(s.sku_out(rec))


@bp.get("/boutique/skus")
def list_skus():
    h.require_role("Customer", "Fitter", "StoreManager", "BillingClerk")
    product_id = h.filter_arg("product_id")

    def pred(r):
        return product_id is None or r["product_id"] == product_id

    return h.list_response("skus", s.sku_out, pred)


@bp.post("/boutique/skus/<sid>/restock")
def restock_sku(sid):
    h.require_role("StoreManager")
    rec = h.lookup("skus", sid)
    body = h.get_body()
    h.require_fields(body, ["quantity"])
    qty = h.require_int(body, "quantity", minimum=1)
    rec["stock_on_hand"] += qty
    store.touch(rec)
    return h.success(s.sku_out(rec))
