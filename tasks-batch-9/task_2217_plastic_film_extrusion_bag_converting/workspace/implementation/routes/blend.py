"""Blend recipes: components, submit, approve, reject, reopen (PRD §3.2-§3.3)."""

from flask import Blueprint, g

import config as C
from auth import ANY_ROLE, endpoint
from errors import ApiError
from num import D
from response import object_response
from services import calc, cascade, refs
from store import serialize, store
from validation import (
    fetch,
    get_enum,
    get_int,
    get_num,
    get_str,
    list_endpoint,
    parse_body,
    require_unique,
    resolve_fks,
)

bp = Blueprint("blend", __name__)

RECIPE_DERIVED_DEFAULTS = {
    "total_weight_pct": 0.0,
    "regrind_pct": 0.0,
    "additive_pct": 0.0,
    "hdpe_pct": 0.0,
    "dominant_polymer_family": None,
    "barrier_layer_present": False,
    "blend_cost_per_kg": 0.0,
    "blended_density_kg_m3": 0.0,
    "strength_index": 0.0,
    "clarity_index": 0.0,
    "slip_index": 0.0,
    "virgin_pcr_pct": 0.0,
    "pcr_band": "LOW",
    "regrind_cap_pct": 0.0,
    "nominal_recycled_content_pct": 0.0,
    "food_contact_eligible": False,
    "pinned_run_count": 0,
    "supersede_pending": False,
}


@bp.post("/blend-recipes")
@endpoint(["BlendEngineer", "PlantAdmin"])
def create_recipe():
    body = parse_body(required=True)
    recipe_code = get_str(body, "recipe_code")
    product_id = get_str(body, "product_id")
    process_type = get_enum(body, "process_type", C.PROCESS_TYPES)
    layer_count = get_int(body, "layer_count", ge=1, le=9)
    supersedes_recipe_id = get_str(body, "supersedes_recipe_id", required=False, default=None)

    resolve_fks({"product_id": product_id, "supersedes_recipe_id": supersedes_recipe_id})
    require_unique(store.blend_recipes, "recipe_code", recipe_code)

    recipe = store.new_common()
    recipe.update(
        {
            "recipe_code": recipe_code,
            "product_id": product_id,
            "supersedes_recipe_id": supersedes_recipe_id,
            "process_type": process_type,
            "layer_count": layer_count,
            "components": [],
            "status": "DRAFT",
            "submitted_by_user_id": None,
            "approved_by_user_id": None,
            "rejection_reason": None,
        }
    )
    recipe.update(dict(RECIPE_DERIVED_DEFAULTS))
    store.blend_recipes[recipe["id"]] = recipe
    return object_response(serialize(recipe), 201)


@bp.get("/blend-recipes/<recipe_id>")
@endpoint(ANY_ROLE)
def read_recipe(recipe_id):
    return object_response(serialize(fetch("blend_recipe", recipe_id)), 200)


@bp.get("/blend-recipes")
@endpoint(ANY_ROLE)
def list_recipes():
    return list_endpoint(
        store.blend_recipes, ("product_id", "supersedes_recipe_id", "status")
    )


@bp.post("/blend-recipes/<recipe_id>/components")
@endpoint(["BlendEngineer"])
def append_component(recipe_id):
    body = parse_body(required=True)
    layer_index = get_int(body, "layer_index")
    component_kind = get_enum(body, "component_kind", C.COMPONENT_KINDS)
    weight_pct = get_num(body, "weight_pct", gt=0)
    resin_grade_id = get_str(body, "resin_grade_id", required=False, default=None)
    if component_kind in ("VIRGIN", "ADDITIVE") and resin_grade_id is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'resin_grade_id' is required for VIRGIN and ADDITIVE components.",
        )
    if component_kind == "REGRIND":
        resin_grade_id = None

    recipe = fetch("blend_recipe", recipe_id)
    resolve_fks({"resin_grade_id": resin_grade_id})

    if recipe["status"] != "DRAFT":
        raise ApiError(
            "ERR_RECIPE_STATE_INVALID",
            "Components may only be appended while the recipe is DRAFT.",
        )
    if layer_index < 1 or layer_index > recipe["layer_count"]:
        raise ApiError(
            "ERR_LAYER_COUNT_MISMATCH",
            "layer_index %s is outside the recipe's layer_count of %s."
            % (layer_index, recipe["layer_count"]),
        )

    recipe["components"].append(
        {
            "layer_index": layer_index,
            "component_kind": component_kind,
            "resin_grade_id": resin_grade_id,
            "weight_pct": weight_pct,
            "position": len(recipe["components"]) + 1,
        }
    )
    calc.recompute_recipe(recipe)
    store.touch(recipe)
    return object_response(serialize(recipe), 201)


@bp.post("/blend-recipes/<recipe_id>/submit")
@endpoint(["BlendEngineer"])
def submit_recipe(recipe_id):
    parse_body(required=False)
    recipe = fetch("blend_recipe", recipe_id)
    if recipe["status"] != "DRAFT":
        raise ApiError("ERR_RECIPE_STATE_INVALID", "Only a DRAFT recipe may be submitted.")

    product = store.products.get(recipe["product_id"])
    calc.recompute_recipe(recipe)

    # band 11 — food-contact compliance
    if product["food_contact_required"] and not calc.recipe_food_contact_resins_ok(recipe):
        raise ApiError(
            "ERR_FOOD_CONTACT_RESIN_INELIGIBLE",
            "Every VIRGIN and ADDITIVE resin must be food_contact_approved for a food-contact product.",
        )

    # band 12 — structural coherence against the product
    if D(recipe["total_weight_pct"]) != D("100.000"):
        raise ApiError(
            "ERR_BLEND_WEIGHT_NOT_100",
            "total_weight_pct is %s; it must be exactly 100.000." % recipe["total_weight_pct"],
        )
    if recipe["layer_count"] != product["required_layer_count"] or any(
        c["layer_index"] < 1 or c["layer_index"] > recipe["layer_count"]
        for c in recipe["components"]
    ):
        raise ApiError(
            "ERR_LAYER_COUNT_MISMATCH",
            "The recipe's layer_count must equal the product's required_layer_count and every layer_index must fall inside it.",
        )
    if D(recipe["regrind_pct"]) > D(recipe["regrind_cap_pct"]):
        raise ApiError(
            "ERR_REGRIND_CAP_EXCEEDED",
            "regrind_pct %s exceeds the regrind cap of %s."
            % (recipe["regrind_pct"], recipe["regrind_cap_pct"]),
        )
    if product["required_layer_count"] >= 3 and not recipe["barrier_layer_present"]:
        raise ApiError(
            "ERR_BARRIER_STRUCTURE_REQUIRED",
            "A product requiring three or more layers needs a barrier component.",
        )
    if D(recipe["strength_index"]) < D(product["min_strength_index"]):
        raise ApiError(
            "ERR_STRENGTH_INDEX_BELOW_MIN",
            "strength_index %s is below the product minimum of %s."
            % (recipe["strength_index"], product["min_strength_index"]),
        )

    recipe["status"] = "SUBMITTED"
    recipe["submitted_by_user_id"] = g.user_id
    recipe["rejection_reason"] = None
    store.touch(recipe)
    return object_response(serialize(recipe), 200)


@bp.post("/blend-recipes/<recipe_id>/approve")
@endpoint(["QualityManager"])
def approve_recipe(recipe_id):
    parse_body(required=False)
    recipe = fetch("blend_recipe", recipe_id)
    if recipe["status"] != "SUBMITTED":
        raise ApiError("ERR_RECIPE_STATE_INVALID", "Only a SUBMITTED recipe may be approved.")

    predecessor = None
    if recipe.get("supersedes_recipe_id"):
        predecessor = store.blend_recipes.get(recipe["supersedes_recipe_id"])
        if predecessor is None or predecessor["status"] != "APPROVED":
            raise ApiError(
                "ERR_RECIPE_NOT_APPROVED",
                "The superseded predecessor recipe must be in APPROVED status.",
            )

    if g.user_id == recipe.get("submitted_by_user_id"):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The operator who submitted this recipe may not approve it.",
        )

    if predecessor is not None and predecessor["product_id"] != recipe["product_id"]:
        raise ApiError(
            "ERR_PRODUCT_MISMATCH",
            "The superseded predecessor recipe targets a different product.",
        )

    recipe["status"] = "APPROVED"
    recipe["approved_by_user_id"] = g.user_id
    store.touch(recipe)

    if predecessor is not None:
        calc.recompute_pinned_run_count(predecessor)
        if predecessor["pinned_run_count"] == 0:
            predecessor["status"] = "SUPERSEDED"
            predecessor["supersede_pending"] = False
        else:
            predecessor["supersede_pending"] = True
        store.touch(predecessor)

    return object_response(serialize(recipe), 200)


@bp.post("/blend-recipes/<recipe_id>/reject")
@endpoint(["QualityManager"])
def reject_recipe(recipe_id):
    body = parse_body(required=True)
    rejection_reason = get_str(body, "rejection_reason")
    recipe = fetch("blend_recipe", recipe_id)
    if recipe["status"] != "SUBMITTED":
        raise ApiError("ERR_RECIPE_STATE_INVALID", "Only a SUBMITTED recipe may be rejected.")
    if g.user_id == recipe.get("submitted_by_user_id"):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The operator who submitted this recipe may not reject it.",
        )
    recipe["status"] = "REJECTED"
    recipe["rejection_reason"] = rejection_reason
    store.touch(recipe)
    return object_response(serialize(recipe), 200)


@bp.post("/blend-recipes/<recipe_id>/reopen")
@endpoint(["BlendEngineer"])
def reopen_recipe(recipe_id):
    parse_body(required=False)
    recipe = fetch("blend_recipe", recipe_id)
    if recipe["status"] != "REJECTED":
        raise ApiError("ERR_RECIPE_STATE_INVALID", "Only a REJECTED recipe may be reopened.")
    calc.recompute_pinned_run_count(recipe)
    if recipe["pinned_run_count"] > 0:
        raise ApiError(
            "ERR_RECIPE_STATE_INVALID",
            "This recipe is still pinned by a SCHEDULED, RUNNING or HELD run.",
        )
    recipe["status"] = "DRAFT"
    recipe["submitted_by_user_id"] = None
    recipe["rejection_reason"] = None
    store.touch(recipe)
    return object_response(serialize(recipe), 200)
