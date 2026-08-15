"""Product endpoints."""
from flask import Blueprint, request

import db
import services as svc
from errors import ApiError, ERR_INVALID_STATE, ERR_DISCONTINUE_BLOCKED, ERR_VALIDATION, not_found
from middleware import require_roles
from response import success_object

bp = Blueprint("products", __name__)

ALL_ROLES = ("DistributorAdmin", "FacilityManager", "SalesRep", "FieldTechnician")
CATEGORIES = ("CHEMICAL", "PAPER", "EQUIPMENT", "DISPENSER_SUPPLY", "OTHER")
FAMILIES = ("ACID", "ALKALINE", "NEUTRAL", "OXIDIZER", "NONE")


def product_view(p):
    return dict(p)


@bp.post("/jansan/products")
def create_product():
    require_roles("DistributorAdmin")
    body = request.get_json(silent=True) or {}
    sku = svc.as_str(svc.require_field(body, "sku"), "sku")
    name = svc.as_str(svc.require_field(body, "name"), "name")
    category = svc.as_enum(svc.require_field(body, "category"), "category", CATEGORIES)
    base_price = svc.as_int(svc.require_field(body, "base_price_cents"), "base_price_cents")
    uom = svc.as_str(svc.require_field(body, "unit_of_measure"), "unit_of_measure")
    qty_on_hand = svc.as_int(svc.require_field(body, "qty_on_hand"), "qty_on_hand", minimum=0)
    dilution = body.get("dilution_required", False)
    if not isinstance(dilution, bool):
        raise ApiError(ERR_VALIDATION, "dilution_required must be a boolean", 400)
    family = body.get("chemical_family", "NONE")
    family = svc.as_enum(family, "chemical_family", FAMILIES)

    # sku uniqueness
    for p in db.products.values():
        if p["sku"] == sku:
            raise ApiError(ERR_VALIDATION, "sku must be unique", 400)

    p = svc.base_resource()
    p.update({
        "sku": sku,
        "name": name,
        "category": category,
        "base_price_cents": base_price,
        "unit_of_measure": uom,
        "dilution_required": dilution,
        "chemical_family": family,
        "qty_on_hand": qty_on_hand,
        "qty_allocated": 0,
        "status": "ACTIVE",
    })
    db.products[p["id"]] = p
    return success_object(product_view(p), 201)


def get_product_or_404(product_id):
    p = db.products.get(product_id)
    if p is None:
        raise not_found("Product not found")
    return p


@bp.get("/jansan/products/<product_id>")
def get_product(product_id):
    require_roles(*ALL_ROLES)
    p = get_product_or_404(product_id)
    return success_object(product_view(p))


@bp.post("/jansan/products/<product_id>/declare-shortage")
def declare_shortage(product_id):
    require_roles("DistributorAdmin")
    p = get_product_or_404(product_id)
    if p["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Product is not ACTIVE", 409)
    p["status"] = "SHORTAGE"
    svc.run_shortage_cascade(p)
    svc.touch(p)
    return success_object(product_view(p))


@bp.post("/jansan/products/<product_id>/resolve-shortage")
def resolve_shortage(product_id):
    require_roles("DistributorAdmin")
    p = get_product_or_404(product_id)
    if p["status"] != "SHORTAGE":
        raise ApiError(ERR_INVALID_STATE, "Product is not SHORTAGE", 409)
    p["status"] = "ACTIVE"
    svc.touch(p)
    return success_object(product_view(p))


@bp.post("/jansan/products/<product_id>/discontinue")
def discontinue_product(product_id):
    require_roles("DistributorAdmin")
    p = get_product_or_404(product_id)
    if p["status"] not in ("ACTIVE", "SHORTAGE"):
        raise ApiError(ERR_INVALID_STATE, "Product cannot be discontinued from current state", 409)
    for line in db.order_lines.values():
        if line["product_id"] == p["id"] and line["status"] in ("PENDING", "ALLOCATED", "SUBSTITUTION_PENDING"):
            raise ApiError(ERR_DISCONTINUE_BLOCKED, "Product has open order lines", 409)
    p["status"] = "DISCONTINUED"
    svc.touch(p)
    return success_object(product_view(p))
