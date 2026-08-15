"""Recipe endpoints."""
from decimal import Decimal
from flask import Blueprint, request

import db
import errors
from middleware import require_role
from response import success_object, success_list
from services.common import (
    new_id,
    now_iso,
    pagination_params,
    paginate,
    sort_by_created_at,
    serialize_recipe,
    to_decimal,
    to_int,
)
from services.calculations import compute_highest_component_ghs, GHS_CLASSES

bp = Blueprint("recipes", __name__)

FRACTION_SUM_TOL = Decimal("0.000001")


def _validate_components(components):
    """Returns list of (material_code, mass_fraction_pct_decimal, charge_order) or raises.
    Validates only shape; fraction sum and charge_order uniqueness separately.
    """
    if not isinstance(components, list) or len(components) == 0:
        raise errors.ApiError(errors.ERR_RECIPE_FRACTION_SUM_INVALID, 422, "components must be non-empty list")
    parsed = []
    for comp in components:
        if not isinstance(comp, dict):
            raise errors.invalid_request("each component must be an object")
        mc = comp.get("material_code")
        if not mc or not isinstance(mc, str):
            raise errors.invalid_request("component.material_code required")
        mf = comp.get("mass_fraction_pct")
        mf_d = to_decimal(mf, "mass_fraction_pct")
        co = comp.get("charge_order")
        co_i = to_int(co, "charge_order")
        parsed.append({
            "material_code": mc,
            "mass_fraction_pct": float(mf_d),
            "charge_order": co_i,
        })
    return parsed


def _check_fraction_sum(components):
    total = sum(Decimal(str(c["mass_fraction_pct"])) for c in components)
    if abs(total - Decimal(100)) > FRACTION_SUM_TOL:
        raise errors.ApiError(
            errors.ERR_RECIPE_FRACTION_SUM_INVALID,
            422,
            "mass_fraction_pct must sum to 100.000",
        )


def _check_charge_order(components, err_id=None):
    """charge_order values must be distinct positive integers."""
    seen = set()
    for c in components:
        co = c["charge_order"]
        if co < 1:
            if err_id:
                raise errors.ApiError(err_id, 422, "charge_order must be positive integer")
            raise errors.ApiError(errors.ERR_RECIPE_FRACTION_SUM_INVALID, 422, "charge_order must be positive integer")
        if co in seen:
            if err_id:
                raise errors.ApiError(err_id, 422, "charge_order must be distinct")
            raise errors.ApiError(errors.ERR_RECIPE_FRACTION_SUM_INVALID, 422, "charge_order must be distinct")
        seen.add(co)


def _recipe_or_404(rid):
    r = db.recipes.get(rid)
    if r is None:
        raise errors.not_found("recipe not found")
    return r


@bp.route("/toll-operations/recipes", methods=["POST"])
def create_recipe():
    require_role({"QualityManager"})
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    if not name or not isinstance(name, str):
        raise errors.invalid_request("name required")
    revision = to_int(body.get("revision"), "revision")
    if revision < 1:
        raise errors.invalid_request("revision must be >= 1")
    customer_id = body.get("customer_id")
    if not customer_id or not isinstance(customer_id, str):
        raise errors.invalid_request("customer_id required")
    customer = db.customers.get(customer_id)
    if customer is None:
        raise errors.not_found("customer not found")

    density = to_decimal(body.get("target_density_kg_per_l"), "target_density_kg_per_l")
    if density <= 0:
        raise errors.invalid_request("target_density_kg_per_l must be > 0")
    ypct = to_decimal(body.get("theoretical_yield_pct"), "theoretical_yield_pct")
    if ypct <= 0 or ypct > 100:
        raise errors.invalid_request("theoretical_yield_pct must be in (0, 100]")

    components_raw = body.get("components")
    components = _validate_components(components_raw)
    _check_fraction_sum(components)
    _check_charge_order(components)

    # Compute highest_component_ghs by joining components with customer's lots
    mc_to_ghs = {}
    for lot in db.raw_material_lots.values():
        if lot["customer_id"] == customer_id:
            mc_to_ghs[lot["material_code"]] = lot["ghS_class"]
    highest = compute_highest_component_ghs(components, mc_to_ghs)
    # If no lots at all exist for any component, fall back to NON_HAZ
    if highest is None:
        highest = "NON_HAZ"

    now = now_iso()
    rid = new_id()
    recipe = {
        "id": rid,
        "name": name,
        "revision": revision,
        "customer_id": customer_id,
        "target_density_kg_per_l": float(density),
        "theoretical_yield_pct": float(ypct),
        "components": components,
        "highest_component_ghs": highest,
        "status": "DRAFT",
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.recipes[rid] = recipe
    return success_object(serialize_recipe(recipe), status=201)


@bp.route("/toll-operations/recipes", methods=["GET"])
def list_recipes():
    require_role({"Any"})
    limit, offset = pagination_params()
    rows = list(db.recipes.values())
    customer_id = request.args.get("customer_id")
    if customer_id:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    rows = sort_by_created_at(rows)
    slice_, total = paginate(rows, limit, offset)
    return success_list([serialize_recipe(r) for r in slice_], limit, offset, total)


@bp.route("/toll-operations/recipes/<recipeId>", methods=["GET"])
def get_recipe(recipeId):
    require_role({"Any"})
    r = _recipe_or_404(recipeId)
    return success_object(serialize_recipe(r))


@bp.route("/toll-operations/recipes/<recipeId>/approve", methods=["POST"])
def approve_recipe(recipeId):
    require_role({"QualityManager"})
    r = _recipe_or_404(recipeId)
    if r["status"] != "DRAFT":
        raise errors.invalid_state("recipe not DRAFT")
    # Re-verify composition
    components = r["components"]
    total = sum(Decimal(str(c["mass_fraction_pct"])) for c in components)
    if abs(total - Decimal(100)) > FRACTION_SUM_TOL:
        raise errors.ApiError(errors.ERR_RECIPE_FRACTION_SUM_INVALID, 422, "mass_fraction_pct must sum to 100.000")
    seen = set()
    for c in components:
        co = c["charge_order"]
        if co < 1 or co in seen:
            raise errors.ApiError(errors.ERR_RECIPE_CHARGE_ORDER_INVALID, 422, "charge_order must be distinct positive integers")
        seen.add(co)

    r["status"] = "APPROVED"
    r["version"] += 1
    r["updated_at"] = now_iso()
    return success_object(serialize_recipe(r))


@bp.route("/toll-operations/recipes/<recipeId>/retire", methods=["POST"])
def retire_recipe(recipeId):
    require_role({"QualityManager"})
    r = _recipe_or_404(recipeId)
    if r["status"] != "APPROVED":
        raise errors.invalid_state("recipe not APPROVED")
    open_statuses = {"INTAKE", "RELEASED", "CHARGING", "MIXING", "HOLD_QA"}
    for b in db.batch_jobs.values():
        if b["recipe_id"] == recipeId and b["status"] in open_statuses:
            raise errors.ApiError(errors.ERR_RECIPE_IN_USE, 409, "recipe in use")
    r["status"] = "RETIRED"
    r["version"] += 1
    r["updated_at"] = now_iso()
    return success_object(serialize_recipe(r))
