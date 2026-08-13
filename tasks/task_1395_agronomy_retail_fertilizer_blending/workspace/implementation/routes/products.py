"""Product, PriceSheet, InventoryLot routes."""

from flask import Blueprint, request

import db
from errors import (
    not_found, invalid_transition, validation, business,
    ERR_PRICE_WINDOW_OVERLAP, ERR_PERMIT_NOT_ACTIVE, ERR_STORAGE_CAPACITY_EXCEEDED,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, iso8601_ms
from services.core import scaffold_entity, touch, public, lazy_price_sheet, lazy_permit, now_stamp_helper
from util import (
    get_body, require, optional, reject_unknown, as_string, as_enum, as_int,
    as_number, as_bool, parse_pagination, paginate, parse_instant, D,
)

bp = Blueprint("products", __name__)

FORMS = {"DRY", "LIQUID"}
SEASONS = {"FALL", "SPRING", "SUMMER", "IN_SEASON"}


def _get_product(pid):
    x = db.products.get(pid)
    if x is None:
        raise not_found("Product not found")
    return x


def _get_sheet(sid):
    x = db.price_sheets.get(sid)
    if x is None:
        raise not_found("Price sheet not found")
    return x


def _get_lot(lid):
    x = db.inventory_lots.get(lid)
    if x is None:
        raise not_found("Inventory lot not found")
    return x


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

@bp.post("/agronomy/products")
def create_product():
    require_roles("BranchAdmin")
    body = get_body()
    reject_unknown(body, {"name", "analysis_n_pct", "analysis_p2o5_pct", "analysis_k2o_pct",
                          "form", "regulated_flag"})
    name = as_string(require(body, "name"), "name")
    for other in db.products.values():
        if other["name"] == name:
            raise validation("Product name must be unique")
    n = as_number(require(body, "analysis_n_pct"), "analysis_n_pct", minimum=0)
    p = as_number(require(body, "analysis_p2o5_pct"), "analysis_p2o5_pct", minimum=0)
    k = as_number(require(body, "analysis_k2o_pct"), "analysis_k2o_pct", minimum=0)
    if n > 100 or p > 100 or k > 100:
        raise validation("analysis percentages must be within 0..100")
    form = as_enum(require(body, "form"), "form", FORMS)
    reg = as_bool(optional(body, "regulated_flag", False), "regulated_flag")
    product = scaffold_entity(db.products, {
        "name": name,
        "analysis_n_pct": float(n),
        "analysis_p2o5_pct": float(p),
        "analysis_k2o_pct": float(k),
        "form": form,
        "regulated_flag": reg,
    })
    return success_object(public(product), 201)


@bp.get("/agronomy/products")
def list_products():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.products.values())
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/products/<productId>")
def get_product(productId):
    require_roles(*ALL_ROLES)
    product = _get_product(productId)
    return success_object(public(product))


# ---------------------------------------------------------------------------
# Price sheets
# ---------------------------------------------------------------------------

@bp.post("/agronomy/products/<productId>/price-sheets")
def create_price_sheet(productId):
    require_roles("BranchAdmin")
    product = _get_product(productId)
    body = get_body()
    reject_unknown(body, {"season", "price_per_ton_cents", "effective_from", "effective_to"})
    season = as_enum(require(body, "season"), "season", SEASONS)
    price = as_int(require(body, "price_per_ton_cents"), "price_per_ton_cents", minimum=1)
    eff_from = parse_instant(require(body, "effective_from"), "effective_from")
    eff_to = parse_instant(require(body, "effective_to"), "effective_to")
    if eff_to <= eff_from:
        raise validation("effective_to must be later than effective_from")
    sheet = scaffold_entity(db.price_sheets, {
        "product_id": product["id"],
        "season": season,
        "price_per_ton_cents": price,
        "effective_from": iso8601_ms(eff_from),
        "effective_to": iso8601_ms(eff_to),
        "status": "DRAFT",
    })
    sheet["_effective_from"] = eff_from
    sheet["_effective_to"] = eff_to
    return success_object(public(sheet), 201)


@bp.get("/agronomy/products/<productId>/price-sheets")
def list_price_sheets(productId):
    require_roles(*ALL_ROLES)
    product = _get_product(productId)
    limit, offset = parse_pagination()
    items = [s for s in db.price_sheets.values() if s["product_id"] == product["id"]]
    for s in items:
        lazy_price_sheet(s)
    if "status" in request.args:
        items = [s for s in items if s["status"] == request.args["status"]]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/price-sheets/<priceSheetId>")
def get_price_sheet(priceSheetId):
    require_roles(*ALL_ROLES)
    sheet = _get_sheet(priceSheetId)
    lazy_price_sheet(sheet)
    return success_object(public(sheet))


@bp.post("/agronomy/price-sheets/<priceSheetId>/publish")
def publish_sheet(priceSheetId):
    require_roles("BranchAdmin")
    sheet = _get_sheet(priceSheetId)
    if sheet["status"] != "DRAFT":
        raise invalid_transition("Price sheet not DRAFT")
    # half-open overlap gate against other PUBLISHED sheets of same product
    for other in db.price_sheets.values():
        if other["id"] == sheet["id"] or other["product_id"] != sheet["product_id"]:
            continue
        lazy_price_sheet(other)
        if other["status"] != "PUBLISHED":
            continue
        if sheet["_effective_from"] < other["_effective_to"] and \
                sheet["_effective_to"] > other["_effective_from"]:
            raise business(ERR_PRICE_WINDOW_OVERLAP, 409, "Window overlaps an existing published sheet")
    sheet["status"] = "PUBLISHED"
    touch(sheet)
    return success_object(public(sheet))


@bp.post("/agronomy/price-sheets/<priceSheetId>/expire")
def expire_sheet(priceSheetId):
    require_roles("BranchAdmin")
    sheet = _get_sheet(priceSheetId)
    lazy_price_sheet(sheet)
    if sheet["status"] != "PUBLISHED":
        raise invalid_transition("Price sheet not PUBLISHED")
    sheet["status"] = "EXPIRED"
    touch(sheet)
    return success_object(public(sheet))


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

@bp.get("/agronomy/products/<productId>/inventory-position")
def inventory_position(productId):
    require_roles(*ALL_ROLES)
    product = _get_product(productId)
    lots = [l for l in db.inventory_lots.values() if l["product_id"] == product["id"]]
    on_hand = sum(D(l["on_hand_tons"]) for l in lots)
    reserved = sum(D(l["reserved_tons"]) for l in lots)
    shipped = sum(D(l["shipped_tons"]) for l in lots)
    return success_object({
        "product_id": product["id"],
        "on_hand_tons": float(on_hand),
        "reserved_tons": float(reserved),
        "available_tons": float(on_hand - reserved),
        "shipped_tons": float(shipped),
    })


def _active_permit_for(ptype, site_code):
    for p in db.permits.values():
        if p["permit_type"] != ptype or p["site_code"] != site_code:
            continue
        lazy_permit(p)
        if p["status"] == "ACTIVE":
            return p
    return None


def _active_storage_permit():
    """Any ACTIVE FERTILIZER_STORAGE permit (capacity enforced globally)."""
    for p in db.permits.values():
        if p["permit_type"] != "FERTILIZER_STORAGE":
            continue
        lazy_permit(p)
        if p["status"] == "ACTIVE":
            return p
    return None


@bp.post("/agronomy/inventory-lots")
def receive_lot():
    require_roles("PlantOperator")
    body = get_body()
    reject_unknown(body, {"product_id", "warehouse_code", "received_tons", "lot_cost_cents_per_ton"})
    product_id = require(body, "product_id")
    warehouse_code = as_string(require(body, "warehouse_code"), "warehouse_code")
    received = as_number(require(body, "received_tons"), "received_tons", minimum=0, exclusive_min=True)
    cost = as_int(require(body, "lot_cost_cents_per_ton"), "lot_cost_cents_per_ton", minimum=0)
    # body FK resolution
    product = db.products.get(product_id)
    if product is None:
        raise not_found("Product not found")
    # permit gates
    storage = _active_storage_permit()
    if storage is None:
        raise business(ERR_PERMIT_NOT_ACTIVE, 422, "No ACTIVE FERTILIZER_STORAGE permit")
    if product.get("regulated_flag"):
        # needs ANHYDROUS_STORAGE for the same site as the storage permit
        anh = _active_permit_for("ANHYDROUS_STORAGE", storage["site_code"])
        if anh is None:
            raise business(ERR_PERMIT_NOT_ACTIVE, 422, "No ACTIVE ANHYDROUS_STORAGE permit")
    # capacity
    total_on_hand = sum(D(l["on_hand_tons"]) for l in db.inventory_lots.values())
    if total_on_hand + received > D(storage["max_storage_tons"]):
        raise business(ERR_STORAGE_CAPACITY_EXCEEDED, 422, "Storage capacity exceeded")
    lot = scaffold_entity(db.inventory_lots, {
        "product_id": product["id"],
        "warehouse_code": warehouse_code,
        "received_tons": float(received),
        "on_hand_tons": float(received),
        "reserved_tons": 0,
        "shipped_tons": 0,
        "lot_cost_cents_per_ton": cost,
        "received_at": now_stamp_helper(),
    })
    lot["_received_at"] = db.CLOCK.now()
    return success_object(public(lot), 201)


@bp.get("/agronomy/inventory-lots")
def list_lots():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.inventory_lots.values())
    if "product_id" in request.args:
        items = [l for l in items if l["product_id"] == request.args["product_id"]]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/inventory-lots/<lotId>")
def get_lot(lotId):
    require_roles(*ALL_ROLES)
    lot = _get_lot(lotId)
    return success_object(public(lot))
