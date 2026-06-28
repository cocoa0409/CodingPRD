"""Product endpoints + product-scoped lot list."""
from flask import Blueprint, request

import errors
from db import db, base_versioned
from errors import err
from lookups import body, get_nursery, get_product
from middleware import require_roles, parse_pagination, paginate
from response import ok, created, ok_list
from validation import (req_str, req_enum, opt_enum, req_int_min,
                        opt_int_in_range, opt_int)

bp = Blueprint("products", __name__)

CATEGORIES = {"LIVE_PLANT", "BULK_MATERIAL", "DRY_GOOD"}
UNITS = {"EACH", "CUBIC_YARD"}
LIFECYCLES = {"ANNUAL", "PERENNIAL", "NONE"}


def product_view(p):
    return {
        "id": p["id"],
        "nursery_id": p["nursery_id"],
        "sku": p["sku"],
        "name": p["name"],
        "category": p["category"],
        "unit": p["unit"],
        "lifecycle_class": p["lifecycle_class"],
        "hardiness_min_zone": p["hardiness_min_zone"],
        "hardiness_max_zone": p["hardiness_max_zone"],
        "unit_price_cents": p["unit_price_cents"],
        "warranty_days": p["warranty_days"],
        "warranty_pct": p["warranty_pct"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.post("/nurseries/<nursery_id>/products")
@require_roles("InventoryManager")
def create_product(nursery_id):
    get_nursery(nursery_id)
    data = body()
    sku = req_str(data, "sku")
    name = req_str(data, "name")
    category = req_enum(data, "category", CATEGORIES)
    unit = req_enum(data, "unit", UNITS)
    lifecycle = opt_enum(data, "lifecycle_class", LIFECYCLES, "NONE")
    hmin = opt_int_in_range(data, "hardiness_min_zone", 1, 1, 13)
    hmax = opt_int_in_range(data, "hardiness_max_zone", 13, 1, 13)
    unit_price = req_int_min(data, "unit_price_cents", 0)
    warranty_days = opt_int(data, "warranty_days", 0)
    warranty_pct = opt_int_in_range(data, "warranty_pct", 0, 0, 100)

    if warranty_days < 0:
        err(errors.ERR_INVALID_REQUEST, "warranty_days must be >= 0")

    # unit/category interlock
    if category == "BULK_MATERIAL":
        if unit != "CUBIC_YARD":
            err(errors.ERR_INVALID_REQUEST, "BULK_MATERIAL must use CUBIC_YARD")
    else:
        if unit != "EACH":
            err(errors.ERR_INVALID_REQUEST, "non-BULK_MATERIAL must use EACH")

    # lifecycle/category interlock
    if category == "LIVE_PLANT":
        if lifecycle not in ("ANNUAL", "PERENNIAL"):
            err(errors.ERR_INVALID_REQUEST, "LIVE_PLANT must be ANNUAL or PERENNIAL")
    else:
        if lifecycle != "NONE":
            err(errors.ERR_INVALID_REQUEST, "non-LIVE_PLANT must be NONE")

    if hmin > hmax:
        err(errors.ERR_INVALID_REQUEST, "hardiness_min_zone must be <= max")

    # SKU uniqueness per nursery (priority 6, 409)
    for p in db.products.values():
        if p["nursery_id"] == nursery_id and p["sku"] == sku:
            err(errors.ERR_DUPLICATE_SKU, "SKU already used in this nursery")

    p = base_versioned()
    p.update({
        "nursery_id": nursery_id,
        "sku": sku,
        "name": name,
        "category": category,
        "unit": unit,
        "lifecycle_class": lifecycle,
        "hardiness_min_zone": hmin,
        "hardiness_max_zone": hmax,
        "unit_price_cents": unit_price,
        "warranty_days": warranty_days,
        "warranty_pct": warranty_pct,
    })
    db.products[p["id"]] = p
    return created(product_view(p))


@bp.get("/nurseries/<nursery_id>/products")
@require_roles("InventoryManager", "SalesClerk")
def list_products(nursery_id):
    get_nursery(nursery_id)
    limit, offset = parse_pagination()
    category = request.args.get("category")
    items = [p for p in db.products.values() if p["nursery_id"] == nursery_id]
    if category is not None:
        items = [p for p in items if p["category"] == category]
    items.sort(key=lambda p: p["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([product_view(p) for p in page], limit, offset, total)


@bp.get("/products/<product_id>")
@require_roles("InventoryManager", "SalesClerk")
def read_product(product_id):
    p = get_product(product_id)
    return ok(product_view(p))


@bp.get("/products/<product_id>/inventory-lots")
@require_roles("InventoryManager", "SalesClerk")
def list_product_lots(product_id):
    get_product(product_id)
    limit, offset = parse_pagination()
    from routes.inventory_lots import lot_view
    status = request.args.get("status")
    items = [l for l in db.inventory_lots.values()
             if l["product_id"] == product_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    items.sort(key=lambda l: l["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([lot_view(l) for l in page], limit, offset, total)
