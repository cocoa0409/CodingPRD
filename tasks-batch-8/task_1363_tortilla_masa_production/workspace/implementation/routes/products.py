"""Product endpoints."""
from decimal import Decimal
from flask import Blueprint, request

import domain as D
from db import store, mint, touch
from errors import err
from middleware import authorize, ROLES
from response import ok, ok_list
from validate import body, need_str, need_num, need_int, need_enum, opt_num, paginate

bp = Blueprint("products", __name__)


@bp.post("/plant/products")
def create_product():
    authorize(["PlantManager"])
    b = body()
    sku_code = need_str(b, "sku_code")
    diameter_in = need_enum(b, "diameter_in", D.DIAMETERS)
    count_per_pack = need_int(b, "count_per_pack")
    packs_per_case = need_int(b, "packs_per_case")
    unit_weight_g = need_num(b, "unit_weight_g")
    channel = need_enum(b, "channel", D.PRODUCT_CHANNELS)
    preservative_system = need_enum(b, "preservative_system", D.PRESERVATIVE_SYSTEMS)
    allergen_class = need_enum(b, "allergen_class", D.ALLERGEN_CLASSES)
    weight_tolerance_pct = opt_num(b, "weight_tolerance_pct")
    if weight_tolerance_pct is None:
        weight_tolerance_pct = Decimal("2.0")
    if count_per_pack <= 0:
        err("ERR_INVALID_REQUEST", 400, "count_per_pack must be greater than zero")
    if packs_per_case <= 0:
        err("ERR_INVALID_REQUEST", 400, "packs_per_case must be greater than zero")
    if unit_weight_g <= 0:
        err("ERR_INVALID_REQUEST", 400, "unit_weight_g must be greater than zero")
    if weight_tolerance_pct <= 0:
        err("ERR_INVALID_REQUEST", 400, "weight_tolerance_pct must be greater than zero")
    for p in store.products.values():
        if p["sku_code"] == sku_code:
            err("ERR_DUPLICATE_CODE", 409, "sku_code already exists")
    # Pinned rounding order: per-pack first, then per-case.
    declared_pack_net_g = D.r1(unit_weight_g * Decimal(count_per_pack))
    declared_case_net_g = D.r1(declared_pack_net_g * Decimal(packs_per_case))
    product = mint()
    product.update({
        "sku_code": sku_code, "diameter_in": diameter_in,
        "count_per_pack": count_per_pack, "packs_per_case": packs_per_case,
        "unit_weight_g": unit_weight_g, "channel": channel,
        "preservative_system": preservative_system,
        "shelf_life_days": D.SHELF_LIFE_DAYS[preservative_system],
        "allergen_class": allergen_class,
        "weight_tolerance_pct": weight_tolerance_pct,
        "declared_pack_net_g": declared_pack_net_g,
        "declared_case_net_g": declared_case_net_g,
        "product_status": "ACTIVE",
    })
    store.products[product["id"]] = product
    return ok(D.product_json(product), 201)


@bp.get("/plant/products")
def list_products():
    authorize(ROLES)
    channel = request.args.get("channel")
    allergen_class = request.args.get("allergen_class")
    product_status = request.args.get("product_status")
    items = [p for p in store.products.values()
             if (channel is None or p["channel"] == channel)
             and (allergen_class is None or p["allergen_class"] == allergen_class)
             and (product_status is None or p["product_status"] == product_status)]
    page, limit, offset, total = paginate(items, D.product_json)
    return ok_list(page, limit, offset, total)


@bp.get("/plant/products/<pid>")
def get_product(pid):
    authorize(ROLES)
    return ok(D.product_json(D.get_product(pid)))


@bp.post("/plant/products/<pid>/discontinue")
def discontinue_product(pid):
    authorize(["PlantManager"])
    product = D.get_product(pid)
    if product["product_status"] != "ACTIVE":
        err("ERR_PRODUCT_DISCONTINUED", 409, "Product is not ACTIVE")
    for r in store.runs.values():
        if (r["product_id"] == pid
                and r["production_status"] in ("PLANNED", "SCHEDULED", "IN_PROGRESS")):
            err("ERR_PRODUCT_IN_USE", 409, "Product has runs in PLANNED/SCHEDULED/IN_PROGRESS")
    product["product_status"] = "DISCONTINUED"
    touch(product)
    return ok(D.product_json(product))


@bp.get("/plant/products/<pid>/runs")
def product_runs(pid):
    authorize(ROLES)
    D.get_product(pid)
    items = [r for r in store.runs.values() if r["product_id"] == pid]
    page, limit, offset, total = paginate(items, D.run_json)
    return ok_list(page, limit, offset, total)
