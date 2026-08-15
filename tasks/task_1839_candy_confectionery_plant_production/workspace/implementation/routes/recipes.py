"""Recipe master data (PRD §3.1)."""
from flask import Blueprint

from db import new_id, stamp_new, store
from errors import ApiError
from middleware import ALLERGEN_VOCAB, auth, body, is_num, require_fields
from response import success_object
from serializers import recipe_json

recipes_bp = Blueprint("recipes", __name__)


@recipes_bp.route("/recipes", methods=["POST"])
def create_recipe():
    auth(("ProductionPlanner",))
    b = body()
    # Existence: body FK references must resolve (ERR_NOT_FOUND).
    product_id = b.get("product_id")
    if product_id is not None and product_id not in store.products:
        raise ApiError("ERR_NOT_FOUND", "product_id references a non-existent resource.")
    # Request shape (ERR_INVALID_REQUEST).
    require_fields(b, ["product_id", "name", "shape_code", "cook_temp_min_c", "cook_temp_max_c",
                       "temper_exit_min_c", "temper_exit_max_c", "standard_yield_pct"])
    if not isinstance(b["name"], str) or not b["name"]:
        raise ApiError("ERR_INVALID_REQUEST", "name is required and must be a non-empty string.")
    if not isinstance(b["shape_code"], str) or not b["shape_code"]:
        raise ApiError("ERR_INVALID_REQUEST", "shape_code is required and must be a non-empty string.")
    for f in ("cook_temp_min_c", "cook_temp_max_c", "temper_exit_min_c", "temper_exit_max_c"):
        if not is_num(b[f]):
            raise ApiError("ERR_INVALID_REQUEST", "%s must be a number." % f)
    allergens = b.get("allergens", [])
    if not isinstance(allergens, list) or any(a not in ALLERGEN_VOCAB for a in allergens):
        raise ApiError("ERR_INVALID_REQUEST",
                       "allergens must be a subset of MILK, SOY, PEANUT, TREE_NUT, EGG, WHEAT, SESAME.")
    if not is_num(b["standard_yield_pct"]) or not (0 < b["standard_yield_pct"] <= 1):
        raise ApiError("ERR_INVALID_REQUEST", "standard_yield_pct must be > 0 and <= 1.")
    r = {
        "id": new_id(),
        "product_id": b["product_id"],
        "name": b["name"],
        "shape_code": b["shape_code"],
        "cook_temp_min_c": b["cook_temp_min_c"],
        "cook_temp_max_c": b["cook_temp_max_c"],
        "temper_exit_min_c": b["temper_exit_min_c"],
        "temper_exit_max_c": b["temper_exit_max_c"],
        "allergens": list(allergens),
        "standard_yield_pct": b["standard_yield_pct"],
    }
    stamp_new(r)
    store.recipes[r["id"]] = r
    return success_object(recipe_json(r), 201)
