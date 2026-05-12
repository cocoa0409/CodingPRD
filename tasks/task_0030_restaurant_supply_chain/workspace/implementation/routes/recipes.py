"""Recipes: POST/GET /recipes, GET /recipes/{id}, POST /recipes/{id}/ingredients."""

from flask import Blueprint, request

import db
import errors
import helpers
import response
import serializers
from middleware import auth_required
from services import audit


bp = Blueprint("recipes", __name__, url_prefix="/supply-chain/recipes")


VALID_RECIPE_ZONES = {"AMBIENT", "CHILLED", "FROZEN"}
VALID_EQUIPMENT = {"OVEN", "FRYER", "MIXER", "ASSEMBLY"}


@bp.route("", methods=["POST"])
@auth_required("CentralKitchenPlanner")
def create_recipe():
    body = helpers.get_json_body()
    required = [
        "recipe_code", "name", "temperature_zone",
        "shelf_life_hours", "production_minutes_per_unit",
        "equipment_class", "unit_price_cents",
    ]
    for f in required:
        if f not in body:
            errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, f"Missing field: {f}")

    if body["temperature_zone"] not in VALID_RECIPE_ZONES:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "Invalid temperature_zone.")
    if body["equipment_class"] not in VALID_EQUIPMENT:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "Invalid equipment_class.")

    if not isinstance(body["shelf_life_hours"], int) or body["shelf_life_hours"] <= 0:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "shelf_life_hours must be > 0.")
    if not isinstance(body["production_minutes_per_unit"], (int, float)) or body["production_minutes_per_unit"] <= 0:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "production_minutes_per_unit must be > 0.")
    if not isinstance(body["unit_price_cents"], int) or body["unit_price_cents"] < 0:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "unit_price_cents must be a non-negative integer.")

    rid = db.new_id()
    common = helpers.common_create()
    recipe = {
        "id": rid,
        "recipe_code": body["recipe_code"],
        "name": body["name"],
        "temperature_zone": body["temperature_zone"],
        "shelf_life_hours": body["shelf_life_hours"],
        "production_minutes_per_unit": body["production_minutes_per_unit"],
        "equipment_class": body["equipment_class"],
        "unit_price_cents": body["unit_price_cents"],
        "status": "ACTIVE",
        **common,
    }
    db.recipes[rid] = recipe
    audit.append(target_type="Recipe", target_id=rid, action="CREATE_RECIPE",
                 payload={"recipe_code": recipe["recipe_code"]})
    return response.created(serializers.recipe_dict(recipe))


@bp.route("", methods=["GET"])
@auth_required("PlatformAdmin", "CentralKitchenPlanner", "StoreManager")
def list_recipes():
    limit, offset = helpers.parse_pagination()
    items = list(db.recipes.values())
    status_filter = request.args.get("status")
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]
    items.sort(key=lambda r: r["created_at"])
    page, total = helpers.paginate(items, limit, offset)
    return response.list_ok([serializers.recipe_dict(r) for r in page],
                            limit=limit, offset=offset, total_count=total)


@bp.route("/<rid>", methods=["GET"])
@auth_required("PlatformAdmin", "CentralKitchenPlanner", "StoreManager")
def read_recipe(rid):
    recipe = db.recipes.get(rid)
    if recipe is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Recipe {rid} not found.")
    return response.ok(serializers.recipe_dict(recipe))


@bp.route("/<rid>/ingredients", methods=["POST"])
@auth_required("CentralKitchenPlanner")
def attach_ingredient(rid):
    if rid not in db.recipes:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Recipe {rid} not found.")
    body = helpers.get_json_body()
    if "ingredient_id" not in body or "quantity_per_unit" not in body:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "Missing ingredient_id or quantity_per_unit.")
    iid = body["ingredient_id"]
    qty = body["quantity_per_unit"]
    if iid not in db.ingredients:
        errors.raise_error(errors.ERR_REFERENCE_NOT_FOUND, f"Ingredient {iid} not found.")
    if not isinstance(qty, (int, float)) or qty <= 0:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "quantity_per_unit must be > 0.")

    import clock
    new_id = db.new_id()
    ri = {
        "id": new_id,
        "recipe_id": rid,
        "ingredient_id": iid,
        "quantity_per_unit": qty,
        "created_at": clock.now(),
    }
    db.recipe_ingredients[new_id] = ri
    audit.append(target_type="Recipe", target_id=rid, action="ATTACH_INGREDIENT",
                 payload={"ingredient_id": iid, "quantity_per_unit": qty})
    return response.created(serializers.recipe_ingredient_dict(ri))
