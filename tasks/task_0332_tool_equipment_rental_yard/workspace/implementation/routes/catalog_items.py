"""RentalCatalogItem endpoints (PRD §3.1)."""
from flask import Blueprint, request

import errors
from db import DB, LOCK
from middleware import require_auth
from services.common import (
    new_record, require_body, req_str, req_int, opt_bool, req_enum, get_or_404,
)
from services.booking import catalog_view
from .helpers import get_json_body, list_response, single_response

bp = Blueprint("catalog_items", __name__)

CATEGORIES = {"HAND_TOOL", "POWER_TOOL", "HEAVY_EQUIPMENT"}


@bp.post("/rental-yard/catalog-items")
def create_catalog_item():
    require_auth({"YardManager"})
    body = require_body(get_json_body())

    # Existence (PRD §2.5): referenced rate_card_id checked before business rules.
    rate_card_id = body.get("rate_card_id")
    if not isinstance(rate_card_id, str):
        raise errors.invalid_request("Field 'rate_card_id' must be a string.")
    card = DB.rate_cards.get(rate_card_id)
    if card is None:
        raise errors.not_found()

    sku = req_str(body, "sku", 1, 40)
    name = req_str(body, "name", 1, 120)
    category = req_enum(body, "category", CATEGORIES)
    requires_delivery = opt_bool(body, "requires_delivery", False)
    fuel_capacity = req_int(body, "fuel_capacity_liters", 0)

    with LOCK:
        # rate card must be active at creation (PRD §3.1).
        if not card.get("active", False):
            raise errors.invalid_request("Referenced rate card is not active.")
        # sku unique across all catalog items -> ERR_DUPLICATE_KEY (PRD §3.1).
        for it in DB.catalog_items.values():
            if it["sku"] == sku:
                raise errors.duplicate_key("A catalog item with this sku already exists.")

        rec = new_record({
            "rate_card_id": rate_card_id,
            "sku": sku,
            "name": name,
            "category": category,
            "requires_delivery": requires_delivery,
            "fuel_capacity_liters": fuel_capacity,
        })
        DB.catalog_items[rec["id"]] = rec
    return single_response(rec, 201, view_fn=catalog_view)


@bp.get("/rental-yard/catalog-items/<rid>")
def get_catalog_item(rid):
    rec = get_or_404(DB.catalog_items, rid)
    return single_response(rec, view_fn=catalog_view)


@bp.get("/rental-yard/catalog-items")
def list_catalog_items():
    rate_card_id = request.args.get("rate_card_id")
    category = request.args.get("category")
    items = DB.catalog_items.values()
    if rate_card_id is not None:
        items = [i for i in items if i["rate_card_id"] == rate_card_id]
    if category is not None:
        items = [i for i in items if i["category"] == category]
    return list_response(items, view_fn=catalog_view)
