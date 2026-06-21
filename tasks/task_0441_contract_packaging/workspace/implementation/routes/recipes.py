"""Recipe + BOM line endpoints and the recipe approval state machine
(PRD §3.2)."""
from flask import Blueprint, request

import db
import errors
import response
import serializers
import util
from middleware import require_role, ALL_ROLES
from services import recipe_svc

bp = Blueprint("recipes", __name__)


# ---------------------------------------------------------------------------
# Recipe CRUD
# ---------------------------------------------------------------------------
@bp.route("/copack/recipes", methods=["POST"])
@require_role("Scheduler")
def create_recipe():
    body = util.get_json_body()
    util.require_fields(body, "customer_id", "name", "target_fill_weight_g",
                        "fill_tolerance_pct", "shelf_life_days")
    customer_id = body["customer_id"]
    name = body["name"]
    target = body["target_fill_weight_g"]
    tol = body["fill_tolerance_pct"]
    shelf = body["shelf_life_days"]

    if not isinstance(customer_id, str) or not isinstance(name, str):
        raise errors.invalid_request("customer_id and name must be strings")
    if not util.is_number(target) or not util.is_number(tol):
        raise errors.invalid_request("target_fill_weight_g and fill_tolerance_pct must be numbers")
    if not util.is_int(shelf):
        raise errors.invalid_request("shelf_life_days must be an integer")

    # priority 7: body FK existence (customer_id).
    if customer_id not in db.customers:
        raise errors.not_found("Customer not found")

    # priority 8: target > 0, 0 < tol <= 50, shelf >= 1.
    if target <= 0:
        raise errors.invalid_quantity("target_fill_weight_g must be > 0")
    if not (0 < tol <= 50):
        raise errors.invalid_quantity("fill_tolerance_pct must be > 0 and <= 50")
    if shelf < 1:
        raise errors.invalid_quantity("shelf_life_days must be >= 1")

    rec = db.new_full_record({
        "customer_id": customer_id,
        "name": name,
        "target_fill_weight_g": target,
        "fill_tolerance_pct": tol,
        "shelf_life_days": shelf,
        "allergen_profile": [],
        "status": "DRAFT",
    })
    db.recipes[rec["id"]] = rec
    return response.success(serializers.recipe(rec), status=201)


@bp.route("/copack/recipes/<rid>", methods=["GET"])
@require_role(*ALL_ROLES)
def get_recipe(rid):
    rec = db.recipes.get(rid)
    if rec is None:
        raise errors.not_found("Recipe not found")
    return response.success(serializers.recipe(rec), status=200)


@bp.route("/copack/recipes", methods=["GET"])
@require_role(*ALL_ROLES)
def list_recipes():
    limit, offset = util.parse_pagination()
    customer_id = request.args.get("customer_id")
    items = list(db.recipes.values())
    if customer_id is not None:
        items = [r for r in items if r["customer_id"] == customer_id]
    items = util.sort_by_creation(items)
    window, meta = util.paginate(items, limit, offset)
    return response.success([serializers.recipe(r) for r in window], status=200, pagination=meta)


# ---------------------------------------------------------------------------
# BOM lines
# ---------------------------------------------------------------------------
@bp.route("/copack/recipes/<rid>/bom-lines", methods=["POST"])
@require_role("Scheduler")
def add_bom_line(rid):
    # priority 3: path existence (recipe).
    recipe = db.recipes.get(rid)
    if recipe is None:
        raise errors.not_found("Recipe not found")

    body = util.get_json_body()
    util.require_fields(body, "component_id", "qty_per_unit", "expected_recipe_version")
    component_id = body["component_id"]
    qty_per_unit = body["qty_per_unit"]
    scrap = body.get("scrap_factor_pct", 0)
    expected_version = body["expected_recipe_version"]

    if not isinstance(component_id, str):
        raise errors.invalid_request("component_id must be a string")
    if not util.is_number(qty_per_unit):
        raise errors.invalid_request("qty_per_unit must be a number")
    if scrap is None:
        scrap = 0
    if not util.is_number(scrap):
        raise errors.invalid_request("scrap_factor_pct must be a number")
    if not util.is_int(expected_version):
        raise errors.invalid_request("expected_recipe_version must be an integer")

    # priority 7: body FK existence (component_id).
    if component_id not in db.components:
        raise errors.not_found("Component not found")

    # priority 8: qty_per_unit > 0; scrap_factor_pct in [0, 100).
    if qty_per_unit <= 0:
        raise errors.invalid_quantity("qty_per_unit must be > 0")
    if not (0 <= scrap < 100):
        raise errors.invalid_quantity("scrap_factor_pct must be >= 0 and < 100")

    # priority 20: BOM lines are built while DRAFT (transition-defined state).
    if recipe["status"] != "DRAFT":
        raise errors.invalid_state("Recipe must be DRAFT to add BOM lines")

    # priority 28: OCC on recipe version.
    if expected_version != recipe["version"]:
        raise errors.stale_version("expected_recipe_version does not match recipe version")

    rec = db.new_full_record({
        "recipe_id": rid,
        "component_id": component_id,
        "qty_per_unit": qty_per_unit,
        "scrap_factor_pct": scrap,
    })
    db.bom_lines[rec["id"]] = rec

    # recompute allergen_profile while DRAFT; bump recipe version by 1.
    recipe_svc.recompute_allergen_profile(recipe)
    db.touch(recipe)

    return response.success(serializers.bom_line(rec), status=201)


@bp.route("/copack/recipes/<rid>/bom-lines", methods=["GET"])
@require_role(*ALL_ROLES)
def list_recipe_bom_lines(rid):
    recipe = db.recipes.get(rid)
    if recipe is None:
        raise errors.not_found("Recipe not found")
    limit, offset = util.parse_pagination()
    items = [b for b in db.bom_lines.values() if b["recipe_id"] == rid]
    items = util.sort_by_creation(items)
    window, meta = util.paginate(items, limit, offset)
    return response.success([serializers.bom_line(r) for r in window], status=200, pagination=meta)


@bp.route("/copack/bom-lines/<bid>", methods=["GET"])
@require_role(*ALL_ROLES)
def get_bom_line(bid):
    rec = db.bom_lines.get(bid)
    if rec is None:
        raise errors.not_found("BOM line not found")
    return response.success(serializers.bom_line(rec), status=200)


@bp.route("/copack/bom-lines", methods=["GET"])
@require_role(*ALL_ROLES)
def list_bom_lines():
    limit, offset = util.parse_pagination()
    component_id = request.args.get("component_id")
    recipe_id = request.args.get("recipe_id")
    items = list(db.bom_lines.values())
    if component_id is not None:
        items = [b for b in items if b["component_id"] == component_id]
    if recipe_id is not None:
        items = [b for b in items if b["recipe_id"] == recipe_id]
    items = util.sort_by_creation(items)
    window, meta = util.paginate(items, limit, offset)
    return response.success([serializers.bom_line(r) for r in window], status=200, pagination=meta)


# ---------------------------------------------------------------------------
# Recipe state machine
# ---------------------------------------------------------------------------
def _has_kind(rid, kind):
    return any(
        db.components.get(b["component_id"], {}).get("kind") == kind
        for b in db.bom_lines.values() if b["recipe_id"] == rid
    )


@bp.route("/copack/recipes/<rid>/submit", methods=["POST"])
@require_role("Scheduler")
def submit_recipe(rid):
    recipe = db.recipes.get(rid)
    if recipe is None:
        raise errors.not_found("Recipe not found")
    # priority 20: state precondition.
    if recipe["status"] != "DRAFT":
        raise errors.invalid_state("submit requires recipe DRAFT")
    # business rule: >=1 INGREDIENT and >=1 PACKAGING BOM line.
    if not _has_kind(rid, "INGREDIENT") or not _has_kind(rid, "PACKAGING"):
        raise errors.invalid_state(
            "submit requires at least one INGREDIENT and one PACKAGING BOM line")
    recipe_svc.recompute_allergen_profile(recipe)
    recipe["status"] = "PENDING_APPROVAL"
    db.touch(recipe)
    return response.success(serializers.recipe(recipe), status=200)


@bp.route("/copack/recipes/<rid>/approve", methods=["POST"])
@require_role("QAInspector")
def approve_recipe(rid):
    recipe = db.recipes.get(rid)
    if recipe is None:
        raise errors.not_found("Recipe not found")
    if recipe["status"] != "PENDING_APPROVAL":
        raise errors.invalid_state("approve requires recipe PENDING_APPROVAL")
    recipe["status"] = "APPROVED"
    db.touch(recipe)
    return response.success(serializers.recipe(recipe), status=200)


@bp.route("/copack/recipes/<rid>/reject", methods=["POST"])
@require_role("QAInspector")
def reject_recipe(rid):
    recipe = db.recipes.get(rid)
    if recipe is None:
        raise errors.not_found("Recipe not found")
    if recipe["status"] != "PENDING_APPROVAL":
        raise errors.invalid_state("reject requires recipe PENDING_APPROVAL")
    recipe["status"] = "REJECTED"
    db.touch(recipe)
    return response.success(serializers.recipe(recipe), status=200)


@bp.route("/copack/recipes/<rid>/revise", methods=["POST"])
@require_role("Scheduler")
def revise_recipe(rid):
    recipe = db.recipes.get(rid)
    if recipe is None:
        raise errors.not_found("Recipe not found")
    if recipe["status"] != "REJECTED":
        raise errors.invalid_state("revise requires recipe REJECTED")
    recipe["status"] = "DRAFT"
    db.touch(recipe)
    return response.success(serializers.recipe(recipe), status=200)


@bp.route("/copack/recipes/<rid>/retire", methods=["POST"])
@require_role("Scheduler")
def retire_recipe(rid):
    recipe = db.recipes.get(rid)
    if recipe is None:
        raise errors.not_found("Recipe not found")
    if recipe["status"] != "APPROVED":
        raise errors.invalid_state("retire requires recipe APPROVED")
    # no run referencing this recipe in SCHEDULED/RUNNING/PENDING_QA.
    live = {"SCHEDULED", "RUNNING", "PENDING_QA"}
    for run in db.production_runs.values():
        if run["recipe_id"] == rid and run["status"] in live:
            raise errors.invalid_state("recipe has live production runs")
    recipe["status"] = "RETIRED"
    db.touch(recipe)
    return response.success(serializers.recipe(recipe), status=200)
