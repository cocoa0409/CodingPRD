"""Recipe + RecipeIngredient endpoints."""
from decimal import Decimal

from flask import Blueprint

import db
from db import new_common, new_id, new_log_entry, store, touch
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import created, ok, paginate
from validation import parse_body, require_path_entity

bp = Blueprint("recipes", __name__)

BRAND_TYPES = ["BRANDED", "PRIVATE_LABEL"]
SHAPE_FAMILIES = ["LONG_CUT", "SHORT_CUT", "SPECIALTY"]
DRYING_CURVES = ["STANDARD", "HIGH_TEMP", "LOW_TEMP"]

_RECIPE_SCHEMA = {
    "recipe_name": ("string", True, None),
    "brand_type": ("enum", True, BRAND_TYPES),
    "customer_name": ("string", False, None),
    "shape_family": ("enum", True, SHAPE_FAMILIES),
    "gluten_free": ("boolean", True, None),
    "target_moisture_pct": ("number", True, None),
    "drying_curve": ("enum", True, DRYING_CURVES),
    "shelf_life_days": ("integer", True, None),
    "min_remaining_shelf_life_pct": ("number", False, None),
    "unit_weight_g": ("number", True, None),
    "units_per_case": ("integer", True, None),
    "case_weight_limit_kg": ("number", True, None),
    "cases_per_pallet": ("integer", True, None),
    "ingredients": ("ingredients", True, None),
}


def _positive(body, field):
    if db.dec(body[field]) <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "%s must be > 0" % field)


@bp.post("/recipes")
def create_recipe():
    uid, role, _ = get_context()
    require_roles(["PlantManager"])
    body = parse_body(_RECIPE_SCHEMA, allow_empty=False)
    for field in ("shelf_life_days", "unit_weight_g", "units_per_case",
                  "case_weight_limit_kg", "cases_per_pallet"):
        _positive(body, field)
    if body["brand_type"] == "PRIVATE_LABEL":
        if "customer_name" not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "customer_name is required for PRIVATE_LABEL recipes")
        if "min_remaining_shelf_life_pct" not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "min_remaining_shelf_life_pct is required for PRIVATE_LABEL recipes")
        fraction = db.dec(body["min_remaining_shelf_life_pct"])
        if fraction < 0 or fraction > 1:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "min_remaining_shelf_life_pct must be within [0, 1]")
    else:
        if "customer_name" in body:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "customer_name is forbidden for BRANDED recipes")
        if "min_remaining_shelf_life_pct" in body:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "min_remaining_shelf_life_pct is forbidden for BRANDED recipes")
    recipe = {
        "id": new_id(),
        "recipe_name": body["recipe_name"],
        "brand_type": body["brand_type"],
        "customer_name": body.get("customer_name"),
        "shape_family": body["shape_family"],
        "gluten_free": body["gluten_free"],
        "target_moisture_pct": body["target_moisture_pct"],
        "drying_curve": body["drying_curve"],
        "shelf_life_days": body["shelf_life_days"],
        "min_remaining_shelf_life_pct": body.get("min_remaining_shelf_life_pct"),
        "unit_weight_g": body["unit_weight_g"],
        "units_per_case": body["units_per_case"],
        "case_weight_limit_kg": body["case_weight_limit_kg"],
        "cases_per_pallet": body["cases_per_pallet"],
        "status": "DRAFT",
        "created_by_user_id": uid,
        "approved_by_user_id": None,
    }
    new_common(recipe)
    store.recipes[recipe["id"]] = recipe
    for row in body["ingredients"]:
        ingredient = {
            "id": new_id(),
            "recipe_id": recipe["id"],
            "ingredient_type": row["ingredient_type"],
            "percentage": row["percentage"],
            "min_protein_pct": row.get("min_protein_pct"),
        }
        new_log_entry(ingredient)
        store.recipe_ingredients[ingredient["id"]] = ingredient
    return created(recipe)


def _recipe_ingredients(recipe_id):
    return sorted((r for r in store.recipe_ingredients.values()
                   if r["recipe_id"] == recipe_id),
                  key=lambda r: r.get("_seq", 0))


@bp.get("/recipes")
def list_recipes():
    get_context()
    require_roles(ALL_ROLES)
    rows = list(store.recipes.values())
    rows = paginate.filter(rows, "brand_type")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/recipes/<recipe_id>")
def get_recipe(recipe_id):
    get_context()
    require_roles(ALL_ROLES)
    return ok(require_path_entity(store.recipes, recipe_id, "ERR_RECIPE_NOT_FOUND"))


@bp.get("/recipes/<recipe_id>/ingredients")
def list_recipe_ingredients(recipe_id):
    get_context()
    require_roles(ALL_ROLES)
    recipe = require_path_entity(store.recipes, recipe_id, "ERR_RECIPE_NOT_FOUND")
    return ok(paginate(_recipe_ingredients(recipe["id"])), rtype="array", pagination=paginate)


@bp.post("/recipes/<recipe_id>/approve")
def approve_recipe(recipe_id):
    uid, role, _ = get_context()
    require_roles(["QAManager"])
    recipe = require_path_entity(store.recipes, recipe_id, "ERR_RECIPE_NOT_FOUND")
    if uid == recipe["created_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "Approver must differ from the recipe creator")
    if recipe["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a DRAFT recipe can be approved")
    rows = _recipe_ingredients(recipe["id"])
    total = sum((db.dec(r["percentage"]) for r in rows), Decimal("0"))
    if not rows or total != Decimal("100.00"):
        raise ApiError("ERR_RECIPE_FORMULA_INVALID", 422,
                       "Recipe requires >= 1 ingredient row with percentages summing to exactly 100.00")
    recipe["status"] = "APPROVED"
    recipe["approved_by_user_id"] = uid
    touch(recipe)
    return ok(recipe)


@bp.post("/recipes/<recipe_id>/amend")
def amend_recipe(recipe_id):
    get_context()
    require_roles(["PlantManager"])
    recipe = require_path_entity(store.recipes, recipe_id, "ERR_RECIPE_NOT_FOUND")
    body = parse_body({"target_moisture_pct": ("number", True, None)}, allow_empty=False)
    if recipe["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an APPROVED recipe can be amended")
    recipe["target_moisture_pct"] = body["target_moisture_pct"]
    touch(recipe)  # version bump invalidates runs' pinned_recipe_version
    return ok(recipe)


@bp.post("/recipes/<recipe_id>/retire")
def retire_recipe(recipe_id):
    get_context()
    require_roles(["PlantManager"])
    recipe = require_path_entity(store.recipes, recipe_id, "ERR_RECIPE_NOT_FOUND")
    if recipe["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an APPROVED recipe can be retired")
    recipe["status"] = "RETIRED"
    touch(recipe)
    return ok(recipe)
