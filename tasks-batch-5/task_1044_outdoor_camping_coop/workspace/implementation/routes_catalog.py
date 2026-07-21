"""Product catalog endpoints."""
from flask import Blueprint, request

import store
from errors import err
import core as c

bp = Blueprint("catalog", __name__)

CATEGORIES = {"TENT", "SLEEPING", "COOKING", "APPAREL", "CLIMBING", "PADDLE"}


@bp.post("/coop/products")
def create_product():
    ctx = c.authenticate()
    c.authorize(ctx, {"CoopAdmin"})
    body = c.get_body()
    sku = c.require_str(body, "sku")
    name = c.require_str(body, "name")
    category = c.require_enum(body, "category", CATEGORIES)
    retail = c.require_int(body, "retail_price_cents")
    tax_rate = c.require_number(body, "tax_rate")
    replacement = c.require_int(body, "replacement_value_cents")
    is_rentable = body.get("is_rentable", False)
    if not isinstance(is_rentable, bool):
        raise err("ERR_VALIDATION", "is_rentable must be a boolean")
    base_daily = c.opt_int(body, "base_daily_rate_cents", 0)
    if is_rentable and base_daily <= 0:
        raise err("ERR_VALIDATION", "base_daily_rate_cents must be > 0 for a rentable product")
    for p in store.products.values():
        if p["sku"] == sku:
            raise err("ERR_VALIDATION", "sku already exists")
    product = {
        "sku": sku,
        "name": name,
        "category": category,
        "retail_price_cents": retail,
        "tax_rate": tax_rate,
        "replacement_value_cents": replacement,
        "is_rentable": is_rentable,
        "base_daily_rate_cents": base_daily,
    }
    store.stamp_new(product)
    store.products[product["id"]] = product
    return c.ok(c.ser_product(product), 201)


@bp.get("/coop/products")
def list_products():
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    category = request.args.get("category")
    is_rentable = request.args.get("is_rentable")
    items = list(store.products.values())
    if category is not None:
        items = [p for p in items if p["category"] == category]
    if is_rentable is not None:
        want = is_rentable.lower() == "true"
        items = [p for p in items if p["is_rentable"] == want]
    return c.paginate_and_serialize(items, c.ser_product)


@bp.get("/coop/products/<pid>")
def get_product(pid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    p = c.lookup("products", pid)
    return c.ok(c.ser_product(p))
