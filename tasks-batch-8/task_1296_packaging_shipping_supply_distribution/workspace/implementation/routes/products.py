"""Product + quantity-break endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
from errors import (err_invalid_request, err_not_found, err_invalid_state,
                    err_stale_version, err_overlapping_price_window)
from middleware import (require_roles, get_json_body, require_str, require_int,
                        optional_bool, optional_number, optional_int)
from response import success_object, success_list, parse_pagination, paginate
from serializers import ser_product, ser_quantity_break
from util import is_int, is_number, to_decimal, parse_datetime

bp = Blueprint("products", __name__)
PREFIX = "/packaging-distribution"

CATEGORIES = {"BOXES", "MAILERS", "TAPE", "CUSHIONING", "LABELS"}
UOMS = {"EACH", "CASE"}
PRODUCT_STATUSES = {"ACTIVE", "DISCONTINUED"}

PRODUCT_READ_ROLES = ("PlatformAdmin", "CatalogManager", "CustomerService",
                      "Buyer", "AccountApprover", "WarehouseOps")


def _get_product(product_id):
    p = db.products.get(product_id)
    if p is None:
        raise err_not_found("Product not found.")
    return p


def _validate_lead_time(is_custom_print, lead_time_days):
    if is_custom_print and lead_time_days <= 0:
        raise err_invalid_request("lead_time_days must be > 0 for custom-print products.")
    if not is_custom_print and lead_time_days != 0:
        raise err_invalid_request("lead_time_days must be 0 for stock products.")


@bp.route(f"{PREFIX}/products", methods=["POST"])
@require_roles("CatalogManager")
def create_product():
    body = get_json_body(required=True)
    sku = require_str(body, "sku")
    name = require_str(body, "name")
    category = require_str(body, "category")
    if category not in CATEGORIES:
        raise err_invalid_request("Field 'category' must be one of BOXES | MAILERS | TAPE | CUSHIONING | LABELS.")
    base_price_cents = require_int(body, "base_price_cents")
    if base_price_cents <= 0:
        raise err_invalid_request("Field 'base_price_cents' must be > 0.")
    uom = require_str(body, "uom")
    if uom not in UOMS:
        raise err_invalid_request("Field 'uom' must be EACH or CASE.")
    case_qty = require_int(body, "case_qty")
    if case_qty < 1:
        raise err_invalid_request("Field 'case_qty' must be >= 1.")
    if uom == "EACH" and case_qty != 1:
        raise err_invalid_request("Field 'case_qty' must be exactly 1 when uom is EACH.")
    pallet_qty = require_int(body, "pallet_qty")
    if pallet_qty < 1:
        raise err_invalid_request("Field 'pallet_qty' must be >= 1.")
    weight = body.get("weight_lbs_per_unit")
    if not is_number(weight):
        raise err_invalid_request("Field 'weight_lbs_per_unit' must be a number.")
    if to_decimal(weight) <= 0:
        raise err_invalid_request("Field 'weight_lbs_per_unit' must be > 0.")
    density = body.get("density_pcf")
    if not is_number(density):
        raise err_invalid_request("Field 'density_pcf' must be a number.")
    if to_decimal(density) <= 0:
        raise err_invalid_request("Field 'density_pcf' must be > 0.")
    oversize = optional_bool(body, "oversize")
    if oversize is None:
        oversize = False
    is_custom_print = optional_bool(body, "is_custom_print")
    if is_custom_print is None:
        is_custom_print = False
    lead_time_days = optional_int(body, "lead_time_days")
    if lead_time_days is None:
        lead_time_days = 0
    if lead_time_days < 0:
        raise err_invalid_request("Field 'lead_time_days' must be >= 0.")
    _validate_lead_time(is_custom_print, lead_time_days)

    if any(p["sku"] == sku for p in db.products.values()):
        raise err_invalid_request("Field 'sku' must be unique across all products.")

    now = db.now()
    p = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "sku": sku,
        "name": name,
        "category": category,
        "base_price_cents": base_price_cents,
        "uom": uom,
        "case_qty": case_qty,
        "pallet_qty": pallet_qty,
        "weight_lbs_per_unit": weight,
        "density_pcf": density,
        "oversize": oversize,
        "is_custom_print": is_custom_print,
        "lead_time_days": lead_time_days,
        "ship_method": "FREIGHT" if oversize else "PARCEL",
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.products[p["id"]] = p
    return success_object(ser_product(p), status=201)


@bp.route(f"{PREFIX}/products", methods=["GET"])
@require_roles(*PRODUCT_READ_ROLES)
def list_products():
    limit, offset = parse_pagination(request.args)
    category_f = request.args.get("category")
    status_f = request.args.get("status")
    custom_f = request.args.get("is_custom_print")
    if category_f is not None and category_f not in CATEGORIES:
        raise err_invalid_request("Invalid 'category' filter.")
    if status_f is not None and status_f not in PRODUCT_STATUSES:
        raise err_invalid_request("Invalid 'status' filter.")
    custom_val = None
    if custom_f is not None:
        if custom_f.lower() == "true":
            custom_val = True
        elif custom_f.lower() == "false":
            custom_val = False
        else:
            raise err_invalid_request("Invalid 'is_custom_print' filter.")
    items = sorted(db.products.values(), key=lambda p: (p["created_at"], p["_seq"]))
    if category_f is not None:
        items = [p for p in items if p["category"] == category_f]
    if status_f is not None:
        items = [p for p in items if p["status"] == status_f]
    if custom_val is not None:
        items = [p for p in items if p["is_custom_print"] == custom_val]
    page, pagination = paginate(items, limit, offset)
    return success_list([ser_product(p) for p in page], pagination)


@bp.route(f"{PREFIX}/products/<product_id>", methods=["GET"])
@require_roles(*PRODUCT_READ_ROLES)
def get_product(product_id):
    return success_object(ser_product(_get_product(product_id)))


@bp.route(f"{PREFIX}/products/<product_id>", methods=["PUT"])
@require_roles("CatalogManager")
def update_product(product_id):
    p = _get_product(product_id)
    body = get_json_body(required=True)
    if p["status"] == "DISCONTINUED":
        raise err_invalid_state("A DISCONTINUED product is read-only.")
    expected = body.get("expected_product_version")
    if expected is None:
        raise err_invalid_request("Missing required field: expected_product_version.")
    if not is_int(expected):
        raise err_invalid_request("Field 'expected_product_version' must be an integer.")
    if expected != p["version"]:
        raise err_stale_version()

    if "name" in body and body["name"] is not None:
        v = body["name"]
        if not isinstance(v, str) or not v:
            raise err_invalid_request("Field 'name' must be a non-empty string.")
        p["name"] = v
    if "base_price_cents" in body and body["base_price_cents"] is not None:
        v = body["base_price_cents"]
        if not is_int(v) or v <= 0:
            raise err_invalid_request("Field 'base_price_cents' must be an integer > 0.")
        p["base_price_cents"] = v
    if "case_qty" in body and body["case_qty"] is not None:
        v = body["case_qty"]
        if not is_int(v) or v < 1:
            raise err_invalid_request("Field 'case_qty' must be an integer >= 1.")
        if p["uom"] == "EACH" and v != 1:
            raise err_invalid_request("Field 'case_qty' must be exactly 1 when uom is EACH.")
        p["case_qty"] = v
    if "pallet_qty" in body and body["pallet_qty"] is not None:
        v = body["pallet_qty"]
        if not is_int(v) or v < 1:
            raise err_invalid_request("Field 'pallet_qty' must be an integer >= 1.")
        p["pallet_qty"] = v
    if "weight_lbs_per_unit" in body and body["weight_lbs_per_unit"] is not None:
        v = body["weight_lbs_per_unit"]
        if not is_number(v) or to_decimal(v) <= 0:
            raise err_invalid_request("Field 'weight_lbs_per_unit' must be a number > 0.")
        p["weight_lbs_per_unit"] = v
    if "density_pcf" in body and body["density_pcf"] is not None:
        v = body["density_pcf"]
        if not is_number(v) or to_decimal(v) <= 0:
            raise err_invalid_request("Field 'density_pcf' must be a number > 0.")
        p["density_pcf"] = v
    if "oversize" in body and body["oversize"] is not None:
        v = body["oversize"]
        if not isinstance(v, bool):
            raise err_invalid_request("Field 'oversize' must be a boolean.")
        p["oversize"] = v
    if "lead_time_days" in body and body["lead_time_days"] is not None:
        v = body["lead_time_days"]
        if not is_int(v) or v < 0:
            raise err_invalid_request("Field 'lead_time_days' must be an integer >= 0.")
        p["lead_time_days"] = v

    _validate_lead_time(p["is_custom_print"], p["lead_time_days"])
    p["ship_method"] = "FREIGHT" if p["oversize"] else "PARCEL"
    db.touch(p)
    return success_object(ser_product(p))


@bp.route(f"{PREFIX}/products/<product_id>/discontinue", methods=["POST"])
@require_roles("CatalogManager")
def discontinue_product(product_id):
    p = _get_product(product_id)
    if p["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE product can be discontinued.")
    live = {"OPEN", "ALLOCATED", "IN_PRODUCTION"}
    if any(l["product_id"] == product_id and l["status"] in live
           for l in db.order_lines.values()):
        raise err_invalid_state("Product has live order pipeline lines.")
    p["status"] = "DISCONTINUED"
    db.touch(p)
    return success_object(ser_product(p))


# ---------------------------------------------------------------------------
# Quantity breaks
# ---------------------------------------------------------------------------
@bp.route(f"{PREFIX}/products/<product_id>/quantity-breaks", methods=["POST"])
@require_roles("CatalogManager")
def create_quantity_break(product_id):
    p = _get_product(product_id)
    body = get_json_body(required=True)
    if p["status"] == "DISCONTINUED":
        raise err_invalid_state("A DISCONTINUED product is read-only.")
    min_qty = require_int(body, "min_qty")
    if min_qty < 1:
        raise err_invalid_request("Field 'min_qty' must be >= 1.")
    unit_price_cents = require_int(body, "unit_price_cents")
    if unit_price_cents <= 0:
        raise err_invalid_request("Field 'unit_price_cents' must be > 0.")
    sort_seq = require_int(body, "sort_seq")
    eff_from_raw = body.get("effective_from")
    if eff_from_raw is None:
        raise err_invalid_request("Missing required field: effective_from.")
    effective_from = parse_datetime(eff_from_raw, "effective_from")
    effective_to = None
    if "effective_to" in body and body["effective_to"] is not None:
        effective_to = parse_datetime(body["effective_to"], "effective_to")
        if effective_to <= effective_from:
            raise err_invalid_request("Field 'effective_to' must be after 'effective_from' (or null).")

    # Overlap rule: same product + same min_qty, half-open windows; adjacency ok.
    for b in db.quantity_breaks.values():
        if b["product_id"] != product_id or b["min_qty"] != min_qty:
            continue
        b_from, b_to = b["effective_from"], b["effective_to"]
        # overlap iff effective_from < b_to (or b_to open) and b_from < effective_to (or open)
        overlap = (b_to is None or effective_from < b_to) and \
                  (effective_to is None or b_from < effective_to)
        if overlap:
            raise err_overlapping_price_window()

    now = db.now()
    brk = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "product_id": product_id,
        "min_qty": min_qty,
        "unit_price_cents": unit_price_cents,
        "sort_seq": sort_seq,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "created_at": now,
    }
    db.quantity_breaks[brk["id"]] = brk
    return success_object(ser_quantity_break(brk), status=201)


@bp.route(f"{PREFIX}/products/<product_id>/quantity-breaks", methods=["GET"])
@require_roles("PlatformAdmin", "CatalogManager", "CustomerService", "Buyer", "AccountApprover")
def list_quantity_breaks(product_id):
    _get_product(product_id)
    limit, offset = parse_pagination(request.args)
    items = [b for b in db.quantity_breaks.values() if b["product_id"] == product_id]
    items.sort(key=lambda b: (b["min_qty"], b["sort_seq"], b["_seq"]))
    page, pagination = paginate(items, limit, offset)
    return success_list([ser_quantity_break(b) for b in page], pagination)


@bp.route(f"{PREFIX}/quantity-breaks/<break_id>", methods=["DELETE"])
@require_roles("CatalogManager")
def delete_quantity_break(break_id):
    brk = db.quantity_breaks.get(break_id)
    if brk is None:
        raise err_not_found("Quantity break not found.")
    del db.quantity_breaks[break_id]
    return "", 204
