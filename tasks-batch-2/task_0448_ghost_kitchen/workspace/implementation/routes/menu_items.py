"""MenuItem + RecipeComponent endpoints (PRD §3.2)."""
from flask import Blueprint

import errors
from db import store
from middleware import get_identity, require_role
from response import object_response, array_response
from services.common import new_entity, serialize, paginate, get_or_404
from validation import get_body, require_str, require_int, require_enum

bp = Blueprint("menu_items", __name__)

EQUIPMENT_TYPES = {"FRYER", "OVEN", "GRILL", "PREP_STATION"}


def _check_brand_owner(role, user_id, brand_id):
    if role == "BrandOwner" and user_id != brand_id:
        raise errors.forbidden()


@bp.route("/menu-items", methods=["POST"])
def create_menu_item():
    user_id, role = get_identity()
    require_role(role, ["BrandOwner"])
    body = get_body()
    brand_id = require_str(body, "brand_id")
    name = require_str(body, "name")
    price_cents = require_int(body, "price_cents")
    prep_minutes = require_int(body, "prep_minutes")
    required_equipment_type = require_enum(body, "required_equipment_type", EQUIPMENT_TYPES)
    with store.lock:
        get_or_404(store.brands, brand_id)
        # Ownership: brand owner must own this brand.
        _check_brand_owner(role, user_id, brand_id)
        if price_cents <= 0:
            raise errors.invalid_request("price_cents must be > 0.")
        if prep_minutes < 1:
            raise errors.invalid_request("prep_minutes must be >= 1.")
        rec = new_entity("MenuItem", {
            "brand_id": brand_id,
            "name": name,
            "price_cents": price_cents,
            "prep_minutes": prep_minutes,
            "required_equipment_type": required_equipment_type,
            "availability": "AVAILABLE",
        })
        store.menu_items[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.route("/menu-items/<mid>", methods=["GET"])
def get_menu_item(mid):
    user_id, role = get_identity()
    require_role(role, ["PlatformOps", "BrandOwner", "StallOperator"])
    with store.lock:
        rec = get_or_404(store.menu_items, mid)
        return object_response(serialize(rec))


@bp.route("/menu-items/<mid>/recipe-components", methods=["POST"])
def create_recipe_component(mid):
    user_id, role = get_identity()
    require_role(role, ["BrandOwner"])
    body = get_body()
    ingredient_name = require_str(body, "ingredient_name")
    quantity_grams = require_int(body, "quantity_grams")
    with store.lock:
        menu_item = get_or_404(store.menu_items, mid)
        # Ownership: brand owner of the item's brand.
        _check_brand_owner(role, user_id, menu_item["brand_id"])
        if quantity_grams <= 0:
            raise errors.invalid_request("quantity_grams must be > 0.")
        # RecipeComponent has only id + created_at (no version/updated_at).
        rec = new_entity("RecipeComponent", {
            "menu_item_id": mid,
            "ingredient_name": ingredient_name,
            "quantity_grams": quantity_grams,
        }, with_version=False)
        store.recipe_components[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.route("/menu-items/<mid>/recipe-components", methods=["GET"])
def list_recipe_components(mid):
    user_id, role = get_identity()
    require_role(role, ["PlatformOps", "BrandOwner", "StallOperator"])
    with store.lock:
        get_or_404(store.menu_items, mid)
        recs = [
            rc for rc in store.recipe_components.values()
            if rc["menu_item_id"] == mid
        ]
        items, limit, offset, total = paginate(recs)
        return array_response(items, limit, offset, total)
