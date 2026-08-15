"""Product endpoints."""

from flask import Blueprint

import db
import errors
import helpers
import middleware
from helpers import (
    get_campaign, get_product, new_id, now_iso, paginate, sort_created,
    req_string, req_int, opt_int, opt_bool,
    serialize_product, serialize_order_line, serialize_supplier_order_line,
)
from middleware import get_body, parse_pagination
from response import success_object, success_list

bp = Blueprint("products", __name__)


@bp.post("/fundraiser/products")
def create_product():
    middleware.require_role("FundraiserAdmin")
    body = get_body(required=True)
    campaign_id = req_string(body, "campaign_id")
    name = req_string(body, "name")
    sku = req_string(body, "sku")
    unit_price = req_int(body, "unit_price_cents", minimum=1)
    unit_cost = req_int(body, "supplier_unit_cost_cents", minimum=0)
    case_pack = req_int(body, "case_pack_size", minimum=1)
    campaign = get_campaign(campaign_id)
    profit_share_bps = opt_int(body, "profit_share_bps", default=None, minimum=0, maximum=10000)
    per_seller_limit = opt_int(body, "per_seller_limit", default=None, minimum=1, allow_null=True)
    returnable = opt_bool(body, "returnable", default=True)
    if campaign["status"] != "DRAFT":
        raise errors.err_invalid_state("Products may only be created while the campaign is DRAFT")
    if profit_share_bps is None:
        profit_share_bps = campaign["default_profit_share_bps"]
    for p in db.products.values():
        if p["campaign_id"] == campaign_id and p["sku"] == sku:
            raise errors.err_duplicate_sku()
    pid = new_id()
    product = {
        "id": pid,
        "campaign_id": campaign_id,
        "name": name,
        "sku": sku,
        "unit_price_cents": unit_price,
        "supplier_unit_cost_cents": unit_cost,
        "case_pack_size": case_pack,
        "profit_share_bps": profit_share_bps,
        "per_seller_limit": per_seller_limit,
        "returnable": returnable,
        "status": "ACTIVE",
        "delivered_units": 0,
        "distributed_units": 0,
        "restocked_units": 0,
        "written_off_units": 0,
        "lost_units": 0,
        "surplus_units": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.products[pid] = product
    return success_object(serialize_product(product), status=201)


@bp.get("/fundraiser/products/<pid>")
def read_product(pid):
    middleware.any_role()
    product = get_product(pid)
    return success_object(serialize_product(product))


@bp.patch("/fundraiser/products/<pid>")
def patch_product(pid):
    middleware.require_role("FundraiserAdmin")
    product = get_product(pid)
    body = get_body(required=True)
    if "expected_product_version" not in body or not isinstance(body.get("expected_product_version"), int) or isinstance(body.get("expected_product_version"), bool):
        raise errors.err_validation("expected_product_version is required and must be an integer")
    expected = body["expected_product_version"]
    new_values = {}
    if "name" in body:
        new_values["name"] = req_string(body, "name")
    if "unit_price_cents" in body:
        new_values["unit_price_cents"] = req_int(body, "unit_price_cents", minimum=1)
    if "supplier_unit_cost_cents" in body:
        new_values["supplier_unit_cost_cents"] = req_int(body, "supplier_unit_cost_cents", minimum=0)
    if "profit_share_bps" in body:
        new_values["profit_share_bps"] = req_int(body, "profit_share_bps", minimum=0, maximum=10000)
    if "per_seller_limit" in body:
        new_values["per_seller_limit"] = opt_int(body, "per_seller_limit", minimum=1, allow_null=True)
    if "returnable" in body:
        new_values["returnable"] = opt_bool(body, "returnable")
    if expected != product["version"]:
        raise errors.err_stale_version()
    campaign = get_campaign(product["campaign_id"])
    if campaign["status"] not in ("DRAFT", "OPEN"):
        raise errors.err_invalid_state("Product catalog may only be edited while the campaign is DRAFT or OPEN")
    for k, v in new_values.items():
        product[k] = v
    helpers.touch(product)
    return success_object(serialize_product(product))


@bp.post("/fundraiser/products/<pid>/discontinue")
def discontinue_product(pid):
    middleware.require_role("FundraiserAdmin")
    product = get_product(pid)
    get_body()
    if product["status"] != "ACTIVE":
        raise errors.err_invalid_state("Product is not ACTIVE")
    campaign = get_campaign(product["campaign_id"])
    if campaign["status"] not in ("DRAFT", "OPEN"):
        raise errors.err_invalid_state("Campaign must be DRAFT or OPEN to discontinue a product")
    product["status"] = "DISCONTINUED"
    helpers.touch(product)
    return success_object(serialize_product(product))


@bp.get("/fundraiser/products/<pid>/order-lines")
def list_product_order_lines(pid):
    middleware.any_role()
    get_product(pid)
    limit, offset = parse_pagination()
    items = sort_created([ln for ln in db.order_lines.values() if ln["product_id"] == pid])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_order_line(ln) for ln in page], limit, offset, total)


@bp.get("/fundraiser/products/<pid>/supplier-order-lines")
def list_product_supplier_order_lines(pid):
    middleware.any_role()
    get_product(pid)
    limit, offset = parse_pagination()
    items = sort_created([ln for ln in db.supplier_order_lines.values() if ln["product_id"] == pid])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_supplier_order_line(ln) for ln in page], limit, offset, total)
