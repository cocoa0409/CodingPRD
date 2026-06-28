"""Product routes: create (DRAFT building block), get, list.

sku must be unique within a campaign (ERR_DUPLICATE_KEY).
"""

from flask import Blueprint, request

import errors
import serializers
from db import db, lock, new_id, now_ts
from middleware import require_roles
from response import success
from helpers import get_body, require_str, require_int, paginate_and_respond
from lookups import get_product
from services import validation

bp = Blueprint("products", __name__)


@bp.route("/fundraising/products", methods=["POST"])
@require_roles("CampaignAdmin")
def create_product():
    body = get_body()
    # priority 4: reference existence of campaign_id
    campaign_id = require_str(body, "campaign_id")
    validation.resolve_campaign_ref(campaign_id)
    # priority 5: body shape
    sku = require_str(body, "sku")
    name = require_str(body, "name")
    unit_price_cents = require_int(body, "unit_price_cents")
    unit_cost_cents = require_int(body, "unit_cost_cents")
    stock_qty = require_int(body, "stock_qty")
    if unit_price_cents < 1:
        raise errors.invalid_request("unit_price_cents must be at least 1")
    if unit_cost_cents < 0 or unit_cost_cents > unit_price_cents:
        raise errors.invalid_request(
            "unit_cost_cents must be >= 0 and <= unit_price_cents")
    if stock_qty < 0:
        raise errors.invalid_request("stock_qty must be at least 0")
    with lock:
        # priority 12: duplicate sku within campaign
        for p in db.products.values():
            if p["campaign_id"] == campaign_id and p["sku"] == sku:
                raise errors.duplicate_key("sku already used in this campaign")
        pid = new_id()
        ts = now_ts()
        product = {
            "id": pid,
            "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": db.next_seq(),
            "campaign_id": campaign_id,
            "sku": sku,
            "name": name,
            "unit_price_cents": unit_price_cents,
            "unit_cost_cents": unit_cost_cents,
            "stock_qty": stock_qty,
        }
        db.products[pid] = product
    return success(serializers.product(product), status=201)


@bp.route("/fundraising/products", methods=["GET"])
@require_roles("CampaignAdmin", "Treasurer", "SchoolOfficial")
def list_products():
    items = list(db.products.values())
    campaign_id = request.args.get("campaign_id")
    if campaign_id is not None:
        items = [p for p in items if p["campaign_id"] == campaign_id]
    return paginate_and_respond(items, serializers.product)


@bp.route("/fundraising/products/<product_id>", methods=["GET"])
@require_roles("CampaignAdmin", "Treasurer", "SchoolOfficial")
def get_product_route(product_id):
    p = get_product(product_id)
    return success(serializers.product(p), status=200)
