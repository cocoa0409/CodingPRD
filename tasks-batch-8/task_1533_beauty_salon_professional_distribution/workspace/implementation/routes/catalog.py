"""Brand, BrandTerritoryExclusive, and Product endpoints."""

from flask import Blueprint, request

import errors as E
import middleware as M
import response as R
import services as S
from db import store, new_id, stamp_created, touch, clock_iso, dt_to_iso

bp = Blueprint("catalog", __name__)

READ_ROLES = S.ALL_ROLES
VARIANT_TYPES = {"BACKBAR", "RETAIL"}
HAZMAT_CLASSES = {"NONE", "AEROSOL", "FLAMMABLE_LIQUID"}
LIFECYCLE_STATES = {"ACTIVE", "DISCONTINUED", "LIQUIDATION", "ARCHIVED"}

LIFECYCLE_TRANSITIONS = {
    ("ACTIVE", "DISCONTINUED"),
    ("DISCONTINUED", "ACTIVE"),
    ("DISCONTINUED", "LIQUIDATION"),
    ("LIQUIDATION", "DISCONTINUED"),
    ("LIQUIDATION", "ARCHIVED"),
}


# ---------------------------------------------------------------------------
# Brands
# ---------------------------------------------------------------------------
@bp.post("/api/brands")
def create_brand():
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"name"})
    name = M.req_string(data, "name")
    M.require_role(ctx, {"DistributionAdmin"})
    for b in store.brands.values():
        if b["name"] == name:
            raise E.duplicate_code("Brand name already in use")
    brand = {
        "id": new_id(),
        "name": name,
        "status": "ACTIVE",
        "discontinued_at": None,
    }
    stamp_created(brand)
    store.brands[brand["id"]] = brand
    return R.success_object(S.pub(brand), 201)


@bp.get("/api/brands")
def list_brands():
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    items = list(store.brands.values())
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.pub_list(page), limit, offset, total)


@bp.get("/api/brands/<bid>")
def get_brand(bid):
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    return R.success_object(S.pub(S.get_brand(bid)))


@bp.post("/api/brands/<bid>/discontinue")
def discontinue_brand(bid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, {"DistributionAdmin"})
    brand = S.get_brand(bid)
    if brand["status"] != "ACTIVE":
        raise E.invalid_request("Brand is already DISCONTINUED")
    brand["status"] = "DISCONTINUED"
    brand["discontinued_at"] = clock_iso()
    touch(brand)
    for product in sorted((p for p in store.products.values() if p["brand_id"] == brand["id"]),
                          key=lambda p: (p.get("created_at") or "", p.get("_seq", 0))):
        if product["lifecycle_status"] == "ACTIVE":
            S.discontinue_product(product)
    return R.success_object(S.pub(brand))


@bp.post("/api/brands/<bid>/territory-exclusives")
def create_exclusive(bid):
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"territory_code", "effective_from", "effective_to"})
    territory_code = M.req_string(data, "territory_code")
    eff_from = M.req_datetime(data, "effective_from")
    eff_to = M.req_datetime(data, "effective_to")
    if not eff_from < eff_to:
        raise E.invalid_time_window("effective_to must be strictly after effective_from")
    M.require_role(ctx, {"DistributionAdmin"})
    brand = S.get_brand(bid)
    for e in store.exclusives.values():
        if e["brand_id"] != brand["id"] or e["territory_code"] != territory_code:
            continue
        # half-open overlap: new.from < existing.to AND existing.from < new.to
        if eff_from < S.parse_dt(e["effective_to"]) and S.parse_dt(e["effective_from"]) < eff_to:
            raise E.territory_window_overlap()
    ex = {
        "id": new_id(),
        "brand_id": brand["id"],
        "territory_code": territory_code,
        "effective_from": dt_to_iso(eff_from),
        "effective_to": dt_to_iso(eff_to),
    }
    stamp_created(ex)
    store.exclusives[ex["id"]] = ex
    return R.success_object(S.pub(ex), 201)


@bp.get("/api/brands/<bid>/territory-exclusives")
def list_exclusives(bid):
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    brand = S.get_brand(bid)
    items = [e for e in store.exclusives.values() if e["brand_id"] == brand["id"]]
    tc = request.args.get("territory_code")
    if tc is not None:
        items = [e for e in items if e["territory_code"] == tc]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.pub_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
@bp.post("/api/products")
def create_product():
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"brand_id", "sku", "name", "variant_type", "hazmat_class",
                        "base_price_cents", "weight_grams"})
    brand_id = M.req_string(data, "brand_id")
    sku = M.req_string(data, "sku")
    name = M.req_string(data, "name")
    variant_type = M.req_enum(data, "variant_type", VARIANT_TYPES)
    hazmat_class = M.req_enum(data, "hazmat_class", HAZMAT_CLASSES)
    base_price = M.req_pos_int(data, "base_price_cents")
    weight = M.req_pos_int(data, "weight_grams")
    M.require_role(ctx, {"DistributionAdmin"})
    brand = S.get_brand(brand_id)
    for p in store.products.values():
        if p["sku"] == sku:
            raise E.duplicate_code("Product sku already in use")
    product = {
        "id": new_id(),
        "brand_id": brand["id"],
        "sku": sku,
        "name": name,
        "variant_type": variant_type,
        "hazmat_class": hazmat_class,
        "base_price_cents": base_price,
        "weight_grams": weight,
        "lifecycle_status": "ACTIVE",
        "discontinued_at": None,
        "liquidation_started_at": None,
    }
    stamp_created(product)
    store.products[product["id"]] = product
    return R.success_object(S.pub(product), 201)


@bp.get("/api/products")
def list_products():
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    items = list(store.products.values())
    brand_id = request.args.get("brand_id")
    if brand_id is not None:
        items = [p for p in items if p["brand_id"] == brand_id]
    ls = request.args.get("lifecycle_status")
    if ls is not None:
        items = [p for p in items if p["lifecycle_status"] == ls]
    vt = request.args.get("variant_type")
    if vt is not None:
        items = [p for p in items if p["variant_type"] == vt]
    hz = request.args.get("hazmat_class")
    if hz is not None:
        items = [p for p in items if p["hazmat_class"] == hz]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.pub_list(page), limit, offset, total)


@bp.get("/api/products/<pid>")
def get_product(pid):
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    return R.success_object(S.pub(S.get_product(pid)))


@bp.post("/api/products/<pid>/lifecycle")
def product_lifecycle(pid):
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"target_status"})
    target = M.req_enum(data, "target_status", LIFECYCLE_STATES)
    M.require_role(ctx, {"DistributionAdmin"})
    product = S.get_product(pid)
    current = product["lifecycle_status"]
    if (current, target) not in LIFECYCLE_TRANSITIONS:
        raise E.invalid_product_state(f"Cannot transition product from {current} to {target}")
    if target == "ACTIVE":
        brand = store.brands.get(product["brand_id"])
        if brand is None or brand["status"] != "ACTIVE":
            raise E.invalid_product_state("Owning brand must be ACTIVE to reactivate")
        product["lifecycle_status"] = "ACTIVE"
        product["discontinued_at"] = None
        touch(product)
    elif target == "DISCONTINUED":
        S.discontinue_product(product)
    elif target == "LIQUIDATION":
        product["lifecycle_status"] = "LIQUIDATION"
        if product["liquidation_started_at"] is None:
            product["liquidation_started_at"] = clock_iso()
        touch(product)
    else:  # ARCHIVED
        product["lifecycle_status"] = "ARCHIVED"
        touch(product)
    return R.success_object(S.pub(product))
