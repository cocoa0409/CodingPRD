from flask import Blueprint
from db import db
from errors import err
from response import ok
from middleware import authenticate, require_role
from services import serialize
from services.common import (
    get_json_body, stamp_create, touch, require_fields, is_str, is_int, is_bool,
)

bp = Blueprint("catalog", __name__)

PRODUCT_TYPES = {"TROPHY", "PLAQUE", "MEDAL", "ACRYLIC", "CRYSTAL"}


def _validate_bom(bom):
    if not isinstance(bom, list):
        raise err("ERR_INVALID_REQUEST", "bom must be an array")
    norm = []
    for entry in bom:
        if not isinstance(entry, dict):
            raise err("ERR_INVALID_REQUEST", "bom entries must be objects")
        if "component_id" not in entry or "qty_per_unit" not in entry:
            raise err("ERR_INVALID_REQUEST", "bom entry requires component_id and qty_per_unit")
        cid = entry["component_id"]
        qpu = entry["qty_per_unit"]
        if not is_str(cid):
            raise err("ERR_INVALID_REQUEST", "component_id must be a string")
        if not is_int(qpu) or qpu < 1:
            raise err("ERR_INVALID_REQUEST", "qty_per_unit must be an integer >= 1")
        norm.append({"component_id": cid, "qty_per_unit": qpu})
    return norm


@bp.route("/catalog-products", methods=["POST"])
def create_product():
    caller = authenticate()
    require_role(caller, ("ShopManager",))
    body = get_json_body()
    require_fields(body, [
        "sku", "name", "product_type", "base_price_cents",
        "engraving_price_per_char_cents", "logo_setup_fee_cents",
        "standard_lead_days", "bom",
    ])
    sku = body["sku"]
    name = body["name"]
    ptype = body["product_type"]
    if not is_str(sku) or not sku.strip():
        raise err("ERR_INVALID_REQUEST", "sku must be a non-empty string")
    if not is_str(name):
        raise err("ERR_INVALID_REQUEST", "name must be a string")
    if ptype not in PRODUCT_TYPES:
        raise err("ERR_INVALID_REQUEST", "invalid product_type")
    for f in ("base_price_cents", "engraving_price_per_char_cents", "logo_setup_fee_cents"):
        if not is_int(body[f]) or body[f] < 0:
            raise err("ERR_INVALID_REQUEST", f"{f} must be an integer >= 0")
    if not is_int(body["standard_lead_days"]) or body["standard_lead_days"] < 1:
        raise err("ERR_INVALID_REQUEST", "standard_lead_days must be an integer >= 1")
    bom = _validate_bom(body["bom"])
    active = body.get("active", True)
    if not is_bool(active):
        raise err("ERR_INVALID_REQUEST", "active must be a boolean")

    # FK existence: bom component_ids must exist
    for entry in bom:
        if entry["component_id"] not in db.components:
            raise err("ERR_NOT_FOUND", "bom references unknown component")

    for p in db.catalog_products.values():
        if p["sku"] == sku:
            raise err("ERR_DUPLICATE_VALUE", "A product with this sku already exists")

    rec = {
        "sku": sku,
        "name": name,
        "product_type": ptype,
        "base_price_cents": body["base_price_cents"],
        "engraving_price_per_char_cents": body["engraving_price_per_char_cents"],
        "logo_setup_fee_cents": body["logo_setup_fee_cents"],
        "standard_lead_days": body["standard_lead_days"],
        "bom": bom,
        "active": active,
    }
    stamp_create(rec)
    db.catalog_products[rec["id"]] = rec
    return ok(serialize.catalog_product(rec), 201)


@bp.route("/catalog-products/<pid>", methods=["GET"])
def get_product(pid):
    caller = authenticate()
    require_role(caller, ("Customer", "ShopStaff", "ShopManager"))
    rec = db.catalog_products.get(pid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Catalog product not found")
    return ok(serialize.catalog_product(rec))


@bp.route("/catalog-products/<pid>", methods=["PATCH"])
def update_product(pid):
    caller = authenticate()
    require_role(caller, ("ShopManager",))
    rec = db.catalog_products.get(pid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Catalog product not found")
    body = get_json_body()
    if "active" in body:
        if not is_bool(body["active"]):
            raise err("ERR_INVALID_REQUEST", "active must be a boolean")
        rec["active"] = body["active"]
    for f in ("base_price_cents", "engraving_price_per_char_cents", "logo_setup_fee_cents"):
        if f in body:
            if not is_int(body[f]) or body[f] < 0:
                raise err("ERR_INVALID_REQUEST", f"{f} must be an integer >= 0")
            rec[f] = body[f]
    if "standard_lead_days" in body:
        if not is_int(body["standard_lead_days"]) or body["standard_lead_days"] < 1:
            raise err("ERR_INVALID_REQUEST", "standard_lead_days must be an integer >= 1")
        rec["standard_lead_days"] = body["standard_lead_days"]
    touch(rec)
    return ok(serialize.catalog_product(rec))
