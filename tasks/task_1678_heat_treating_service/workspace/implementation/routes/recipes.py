"""FurnaceRecipe endpoints."""
from flask import Blueprint

import validation as v
from db import store, new_id, new_common, touch
from errors import ApiError
from middleware import ANY_ROLES, get_context, require_roles
from response import created, ok
from services import domain

bp = Blueprint("recipes", __name__)


@bp.post("/furnace-recipes")
def create_recipe():
    get_context()
    require_roles(["QualityEngineer"])
    body = v.get_body()
    # tier 7 (referential): (alloy_code, spec_code) uniqueness — evaluated before the
    # tier-9 field checks when both key parts are present.
    alloy = body.get("alloy_code")
    spec = body.get("spec_code")
    if isinstance(alloy, str) and isinstance(spec, str):
        for r in store.recipes.values():
            if r["alloy_code"] == alloy and r["spec_code"] == spec:
                raise ApiError("ERR_DUPLICATE_RECIPE", 409,
                               "A recipe with the same (alloy_code, spec_code) already exists")
    # tier 9: required fields / enum validity
    recipe = {
        "id": new_id(),
        "alloy_code": v.req_string(body, "alloy_code"),
        "spec_code": v.req_string(body, "spec_code"),
        "soak_temp_f": v.req_int(body, "soak_temp_f"),
        "soak_tolerance_f": v.req_int(body, "soak_tolerance_f"),
        "min_soak_minutes": v.req_int(body, "min_soak_minutes"),
        "quench_media": v.req_enum(body, "quench_media", domain.QUENCH_MEDIA),
        "required_furnace_class": v.req_enum(body, "required_furnace_class", domain.FURNACE_CLASSES),
        "max_retreats": v.req_int(body, "max_retreats"),
        "fixture_distortion_allowance_in": v.req_number(body, "fixture_distortion_allowance_in"),
        "hardness_min_hrc": v.req_int(body, "hardness_min_hrc"),
        "hardness_max_hrc": v.req_int(body, "hardness_max_hrc"),
        "status": "DRAFT",
    }
    new_common(recipe)
    store.recipes[recipe["id"]] = recipe
    return created(recipe)


@bp.get("/furnace-recipes/<recipe_id>")
def get_recipe(recipe_id):
    get_context()
    require_roles(ANY_ROLES)
    return ok(v.resolve_path(store.recipes, recipe_id, "ERR_RECIPE_NOT_FOUND"))


@bp.post("/furnace-recipes/<recipe_id>/approve")
def approve_recipe(recipe_id):
    get_context()
    require_roles(["QualityEngineer"])
    recipe = v.resolve_path(store.recipes, recipe_id, "ERR_RECIPE_NOT_FOUND")
    # state machine: DRAFT -> APPROVED only; repeat approve is rejected
    if recipe["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_REQUEST", 400, "Recipe is not in DRAFT")
    recipe["status"] = "APPROVED"
    touch(recipe)
    return ok(recipe)
