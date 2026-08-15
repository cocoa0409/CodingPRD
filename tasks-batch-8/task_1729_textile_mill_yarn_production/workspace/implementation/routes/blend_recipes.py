"""BlendRecipe + BlendComponent endpoints.

Approval cascade (PRD §3.1):
  - OCC via expected_recipe_version -> ERR_STALE_VERSION (412)
  - Preconditions: recipe DRAFT, >= 1 component, every lot in {RECEIVED, BLENDED}
  - Side effects: approved_at stamped, projected_cost_per_lb (forward_looking),
    each referenced lot debited and RECEIVED -> BLENDED, exhausted lots -> EXHAUSTED,
    recipe.version + 1.

Supersede: creating a recipe whose recipe_code matches an APPROVED recipe moves
the old one APPROVED -> SUPERSEDED. The code is unique among non-superseded
recipes (DRAFT/REJECTED reuse -> ERR_DUPLICATE_KEY).
"""

from decimal import Decimal

from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import (
    err_duplicate_key,
    err_insufficient_capacity,
    err_invalid_state,
    err_not_found,
    err_reference_not_found,
    err_stale_version,
)
from middleware import require_roles
from response import success_list, success_object
from serializers import serialize_blend_component, serialize_blend_recipe
from services.calculations import projected_cost_per_lb
from services.workflows import (
    components_of_recipe,
    maybe_exhaust_fiber_lot,
    recompute_recipe_totals,
    touch,
)
from validators import (
    apply_filters,
    get_json_body,
    get_pagination,
    req_decimal,
    req_string,
    round2,
    sort_and_paginate,
)

bp = Blueprint("blend_recipes", __name__)

ALL_ROLES = ("MillPlanner", "SpinningSupervisor", "DyeHouseOperator", "QualityInspector", "CustomerServiceRep")


def _get_recipe_or_404(recipe_id):
    recipe = db.blend_recipes.get(recipe_id)
    if recipe is None:
        raise err_not_found("Blend recipe not found")
    return recipe


@bp.post("/mill/blend-recipes")
def create_blend_recipe():
    require_roles("MillPlanner")
    body = get_json_body()
    recipe_code = req_string(body, "recipe_code")
    target_ne = req_decimal(body, "target_yarn_count_ne", min_value=0, min_exclusive=True)

    # Uniqueness (priority 7): code unique among non-superseded recipes, with the
    # deliberate supersede exception — a code held by an APPROVED recipe supersedes it.
    approved_same_code = None
    for r in db.blend_recipes.values():
        if r["recipe_code"] != recipe_code:
            continue
        if r["status"] == "APPROVED":
            approved_same_code = r
        elif r["status"] in ("DRAFT", "REJECTED"):
            raise err_duplicate_key("recipe_code already in use by a non-superseded recipe")

    if approved_same_code is not None:
        approved_same_code["status"] = "SUPERSEDED"
        touch(approved_same_code)

    ts = now_iso()
    record = {
        "id": new_id(),
        "recipe_code": recipe_code,
        "target_yarn_count_ne": target_ne,
        "status": "DRAFT",
        "total_component_weight_lbs": Decimal("0"),
        "projected_cost_per_lb": None,
        "approved_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.blend_recipes[record["id"]] = record
    return success_object(serialize_blend_recipe(record), 201)


@bp.get("/mill/blend-recipes")
def list_blend_recipes():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    items = apply_filters(list(db.blend_recipes.values()), {"status": request.args.get("status")})
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([serialize_blend_recipe(r) for r in page], limit, offset, total)


@bp.get("/mill/blend-recipes/<rid>")
def get_blend_recipe(rid):
    require_roles(*ALL_ROLES)
    return success_object(serialize_blend_recipe(_get_recipe_or_404(rid)))


@bp.post("/mill/blend-recipes/<rid>/components")
def add_component(rid):
    require_roles("MillPlanner")
    recipe = _get_recipe_or_404(rid)
    body = get_json_body()
    fiber_lot_id = req_string(body, "fiber_lot_id")
    weight = req_decimal(body, "component_weight_lbs", min_value=0, min_exclusive=True)

    # Reference existence (priority 4)
    lot = db.fiber_lots.get(fiber_lot_id)
    if lot is None:
        raise err_reference_not_found("fiber_lot_id does not resolve to an existing fiber lot")

    # State legality (priority 5): components may only be added to a DRAFT recipe,
    # and only to lots that can still contribute fiber.
    if recipe["status"] != "DRAFT":
        raise err_invalid_state("Components may only be added while the recipe is DRAFT")
    if lot["status"] not in ("RECEIVED", "BLENDED"):
        raise err_invalid_state("Fiber lot is not in a state that permits blending")

    # Capacity (priority 10)
    if lot["available_weight_lbs"] < weight:
        raise err_insufficient_capacity("Fiber lot lacks available weight for this component")

    record = {
        "id": new_id(),
        "recipe_id": recipe["id"],
        "fiber_lot_id": lot["id"],
        "component_weight_lbs": round2(weight),
        "proportion_pct": Decimal("0"),
        "created_at": now_iso(),
    }
    db.blend_components[record["id"]] = record
    recompute_recipe_totals(recipe)
    touch(recipe)
    return success_object(serialize_blend_component(record), 201)


@bp.get("/mill/blend-recipes/<rid>/components")
def list_components(rid):
    require_roles(*ALL_ROLES)
    recipe = _get_recipe_or_404(rid)
    comps = components_of_recipe(recipe["id"])
    comps = sorted(comps, key=lambda c: (c["created_at"], c["id"]))
    return success_list([serialize_blend_component(c) for c in comps], len(comps), 0, len(comps))


@bp.post("/mill/blend-recipes/<rid>/approve")
def approve_recipe(rid):
    require_roles("MillPlanner")
    recipe = _get_recipe_or_404(rid)
    body = get_json_body()

    # OCC — expected_recipe_version is required on this endpoint (PRD §2.8)
    if "expected_recipe_version" not in body or body["expected_recipe_version"] is None:
        from errors import err_invalid_request
        raise err_invalid_request("Missing required field: expected_recipe_version")
    expected = body["expected_recipe_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        from errors import err_invalid_request
        raise err_invalid_request("expected_recipe_version must be an integer")
    if expected != recipe["version"]:
        raise err_stale_version("expected_recipe_version does not match the recipe's current version")

    # State legality
    if recipe["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT recipe can be approved")
    comps = components_of_recipe(recipe["id"])
    if not comps:
        raise err_invalid_state("Recipe must have at least one component to be approved")
    for comp in comps:
        lot = db.fiber_lots.get(comp["fiber_lot_id"])
        if lot is None or lot["status"] not in ("RECEIVED", "BLENDED"):
            raise err_invalid_state("Every referenced fiber lot must be RECEIVED or BLENDED")

    # Capacity re-check at commitment time (defensive: weights could have shifted)
    for comp in comps:
        lot = db.fiber_lots[comp["fiber_lot_id"]]
        if lot["available_weight_lbs"] < comp["component_weight_lbs"]:
            raise err_insufficient_capacity("Fiber lot lacks available weight for its component")

    # Forward-looking projected cost (Variant A)
    recipe["projected_cost_per_lb"] = projected_cost_per_lb(comps, db.fiber_lots)

    # Debit each lot, transition RECEIVED -> BLENDED, then maybe EXHAUSTED
    for comp in comps:
        lot = db.fiber_lots[comp["fiber_lot_id"]]
        lot["available_weight_lbs"] = round2(lot["available_weight_lbs"] - comp["component_weight_lbs"])
        if lot["status"] == "RECEIVED":
            lot["status"] = "BLENDED"
        touch(lot)
        maybe_exhaust_fiber_lot(lot)

    recipe["status"] = "APPROVED"
    recipe["approved_at"] = now_iso()
    touch(recipe)
    return success_object(serialize_blend_recipe(recipe))


@bp.post("/mill/blend-recipes/<rid>/reject")
def reject_recipe(rid):
    require_roles("MillPlanner")
    recipe = _get_recipe_or_404(rid)
    if recipe["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT recipe can be rejected")
    # Detach (delete) all components; no fiber lot weight changes.
    for comp in components_of_recipe(recipe["id"]):
        del db.blend_components[comp["id"]]
    recipe["total_component_weight_lbs"] = Decimal("0")
    recipe["status"] = "REJECTED"
    touch(recipe)
    return success_object(serialize_blend_recipe(recipe))
