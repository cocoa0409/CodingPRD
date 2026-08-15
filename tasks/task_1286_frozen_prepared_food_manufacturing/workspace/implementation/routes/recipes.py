"""Recipes, BOM components, approval cycle, scale-up preview (PRD §3.1)."""

from decimal import Decimal

from flask import request

import services as svc
from db import STORE, bump, new_record
from errors import ApiError
from middleware import PLANT_ROLES, endpoint
from response import list_response, ok_object
from routes import bp
from serializers import component_out, recipe_out
from util import (
    COMPONENT_TYPES,
    PRODUCT_STYLES,
    SCALE_MAX,
    SCALE_MIN,
    UNITS_OF_MEASURE,
    as_enum,
    as_positive_decimal,
    as_positive_int,
    as_string,
    body_dict,
    fnum,
    opt_present,
    q3,
    req_present,
)


# ---------------------------------------------------------------------------
# Recipe CRUD
# ---------------------------------------------------------------------------

@bp.route("/plant/recipes", methods=["POST"])
@endpoint({"PlantManager"})
def create_recipe(user_id, role):
    body = body_dict(request.get_json(silent=True))
    name = as_string(req_present(body, "name"), "name")
    product_style = as_enum(req_present(body, "product_style"), "product_style", PRODUCT_STYLES)
    base_yield = as_positive_int(req_present(body, "base_batch_yield_units"), "base_batch_yield_units")
    portion = as_positive_decimal(req_present(body, "portion_weight_g"), "portion_weight_g")
    shelf = as_positive_int(req_present(body, "shelf_life_days"), "shelf_life_days")
    rec = new_record()
    rec.update(
        name=name,
        product_style=product_style,
        base_batch_yield_units=base_yield,
        portion_weight_g=portion,
        shelf_life_days=shelf,
        status="DRAFT",
    )
    STORE["recipes"][rec["id"]] = rec
    return ok_object(recipe_out(rec), 201)


@bp.route("/plant/recipes", methods=["GET"])
@endpoint(PLANT_ROLES)
def list_recipes(user_id, role):
    status = request.args.get("status")
    recs = list(STORE["recipes"].values())
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return list_response(recs, recipe_out)


@bp.route("/plant/recipes/<recipeId>", methods=["GET"])
@endpoint(PLANT_ROLES)
def get_recipe(user_id, role, recipeId):
    return ok_object(recipe_out(svc.require_record("recipes", recipeId, "Recipe")))


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------

def _validate_parent(recipe, parent_id):
    """parent_component_id: null (top-level) or a component of the same recipe."""
    if parent_id is None:
        return None
    if not isinstance(parent_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'parent_component_id' must be a string")
    parent = STORE["components"].get(parent_id)
    if parent is None:
        raise ApiError("ERR_NOT_FOUND", "Parent component does not exist")
    if parent["recipe_id"] != recipe["id"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "parent_component_id must reference a component of the same recipe",
        )
    return parent_id


@bp.route("/plant/recipes/<recipeId>/components", methods=["POST"])
@endpoint({"PlantManager"})
def add_component(user_id, role, recipeId):
    body = body_dict(request.get_json(silent=True))
    name = as_string(req_present(body, "component_name"), "component_name")
    ctype = as_enum(req_present(body, "component_type"), "component_type", COMPONENT_TYPES)
    qty = as_positive_decimal(
        req_present(body, "quantity_per_base_batch"), "quantity_per_base_batch"
    )
    uom = as_enum(req_present(body, "unit_of_measure"), "unit_of_measure", UNITS_OF_MEASURE)
    scale_exp = Decimal("1.0")
    if body.get("scale_exponent") is not None:
        scale_exp = as_positive_decimal(body["scale_exponent"], "scale_exponent")
        if scale_exp > Decimal("1.5"):
            raise ApiError("ERR_INVALID_REQUEST", "Field 'scale_exponent' must be <= 1.5")
    allergen = body.get("allergen_tag")
    if allergen is not None and not isinstance(allergen, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'allergen_tag' must be a string")
    parent_id = None
    if body.get("parent_component_id") is not None:
        parent_id = as_string(body["parent_component_id"], "parent_component_id")

    recipe = svc.require_record("recipes", recipeId, "Recipe")
    # body FK existence (pipeline stage 6) before state (stage 8)
    if parent_id is not None:
        parent = STORE["components"].get(parent_id)
        if parent is None:
            raise ApiError("ERR_NOT_FOUND", "Parent component does not exist")
        if parent["recipe_id"] != recipe["id"]:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "parent_component_id must reference a component of the same recipe",
            )
    if recipe["status"] != "DRAFT":
        raise ApiError("ERR_RECIPE_STATE", "Components may be added only while the recipe is DRAFT")

    rec = new_record()
    rec.update(
        recipe_id=recipe["id"],
        parent_component_id=parent_id,
        component_name=name,
        component_type=ctype,
        quantity_per_base_batch=qty,
        unit_of_measure=uom,
        scale_exponent=scale_exp,
        allergen_tag=allergen,
    )
    STORE["components"][rec["id"]] = rec
    return ok_object(component_out(rec), 201)


@bp.route("/plant/components", methods=["GET"])
@endpoint(PLANT_ROLES)
def list_components(user_id, role):
    recipe_id = request.args.get("recipe_id")
    parent_id = request.args.get("parent_component_id")
    recs = list(STORE["components"].values())
    if recipe_id is not None:
        recs = [c for c in recs if c["recipe_id"] == recipe_id]
    if parent_id is not None:
        recs = [c for c in recs if c["parent_component_id"] == parent_id]
    return list_response(recs, component_out)


@bp.route("/plant/components/<componentId>", methods=["GET"])
@endpoint(PLANT_ROLES)
def get_component(user_id, role, componentId):
    return ok_object(component_out(svc.require_record("components", componentId, "Component")))


@bp.route("/plant/components/<componentId>", methods=["PATCH"])
@endpoint({"PlantManager"})
def reparent_component(user_id, role, componentId):
    body = body_dict(request.get_json(silent=True))
    if "parent_component_id" not in body:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: parent_component_id")
    new_parent = body["parent_component_id"]
    if new_parent is not None and not isinstance(new_parent, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'parent_component_id' must be a string")

    comp = svc.require_record("components", componentId, "Component")
    if new_parent is not None:
        parent = STORE["components"].get(new_parent)
        if parent is None:
            raise ApiError("ERR_NOT_FOUND", "Parent component does not exist")
        if parent["recipe_id"] != comp["recipe_id"]:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "parent_component_id must reference a component of the same recipe",
            )
    recipe = STORE["recipes"].get(comp["recipe_id"])
    if recipe is None or recipe["status"] != "DRAFT":
        raise ApiError(
            "ERR_RECIPE_STATE", "Components may be re-parented only while the recipe is DRAFT"
        )
    comp["parent_component_id"] = new_parent
    bump(comp)
    return ok_object(component_out(comp))


# ---------------------------------------------------------------------------
# Approval cycle
# ---------------------------------------------------------------------------

def _component_graph_acyclic(recipe_id):
    """Cycle detection over parent_component_id within one recipe."""
    comps = svc.components_of_recipe(recipe_id)
    by_id = {c["id"]: c for c in comps}
    for c in comps:
        seen = set()
        cur = c
        while cur is not None and cur["parent_component_id"] is not None:
            pid = cur["parent_component_id"]
            if pid in seen or pid == c["id"]:
                return False
            seen.add(cur["id"])
            cur = by_id.get(pid)
        # self-loop check
        if c["parent_component_id"] == c["id"]:
            return False
    return True


def _recipe_has_nonterminal_batch(recipe_id):
    for order in svc.orders_of_recipe(recipe_id):
        for b in svc.batches_of_order(order["id"]):
            if b["status"] not in svc.BATCH_TERMINAL:
                return True
    return False


@bp.route("/plant/recipes/<recipeId>/approve", methods=["POST"])
@endpoint({"PlantManager"})
def approve_recipe(user_id, role, recipeId):
    recipe = svc.require_record("recipes", recipeId, "Recipe")
    if recipe["status"] != "DRAFT":
        raise ApiError("ERR_RECIPE_STATE", "Only a DRAFT recipe can be approved")
    if not svc.components_of_recipe(recipe["id"]):
        raise ApiError("ERR_RECIPE_NO_COMPONENTS", "Approve requires at least one BOM component")
    if not _component_graph_acyclic(recipe["id"]):
        raise ApiError(
            "ERR_RECIPE_COMPONENT_CYCLE", "parent_component_id graph contains a cycle"
        )
    recipe["status"] = "APPROVED"
    bump(recipe)
    return ok_object(recipe_out(recipe))


@bp.route("/plant/recipes/<recipeId>/revise", methods=["POST"])
@endpoint({"PlantManager"})
def revise_recipe(user_id, role, recipeId):
    recipe = svc.require_record("recipes", recipeId, "Recipe")
    if recipe["status"] != "APPROVED":
        raise ApiError("ERR_RECIPE_STATE", "Only an APPROVED recipe can be revised")
    if _recipe_has_nonterminal_batch(recipe["id"]):
        raise ApiError("ERR_RECIPE_BUSY", "A batch of this recipe is in a non-terminal state")
    recipe["status"] = "DRAFT"
    bump(recipe)
    return ok_object(recipe_out(recipe))


@bp.route("/plant/recipes/<recipeId>/retire", methods=["POST"])
@endpoint({"PlantManager"})
def retire_recipe(user_id, role, recipeId):
    recipe = svc.require_record("recipes", recipeId, "Recipe")
    if recipe["status"] == "RETIRED":
        raise ApiError("ERR_RECIPE_STATE", "Recipe is already RETIRED")
    if recipe["status"] == "APPROVED" and _recipe_has_nonterminal_batch(recipe["id"]):
        raise ApiError("ERR_RECIPE_BUSY", "A batch of this recipe is in a non-terminal state")
    recipe["status"] = "RETIRED"
    bump(recipe)
    return ok_object(recipe_out(recipe))


# ---------------------------------------------------------------------------
# Scale-up preview (SCAFFOLD §1.3 recipe_scale_up)
# ---------------------------------------------------------------------------

def _topological_order(recipe_id):
    """Parents before children over parent_component_id; creation order among
    peers. Cyclic leftovers (possible pre-approval) appended in creation order."""
    comps = sorted(svc.components_of_recipe(recipe_id), key=lambda c: c["_seq"])
    by_parent = {}
    for c in comps:
        by_parent.setdefault(c["parent_component_id"], []).append(c)
    ordered = []
    visited = set()
    queue = [c for c in comps if c["parent_component_id"] is None or c["parent_component_id"] not in {x["id"] for x in comps}]
    # roots first: null parent or parent outside this recipe
    while queue:
        node = queue.pop(0)
        if node["id"] in visited:
            continue
        visited.add(node["id"])
        ordered.append(node)
        queue.extend(by_parent.get(node["id"], []))
    for c in comps:  # cyclic leftovers
        if c["id"] not in visited:
            ordered.append(c)
    return ordered


def _effective_exponent(comp, by_id):
    """Product of scale_exponent along the ancestor chain, root down to and
    including comp; a PACKAGING component's own exponent is forced to 1.0."""
    chain = []
    cur = comp
    seen = set()
    while cur is not None and cur["id"] not in seen:
        seen.add(cur["id"])
        chain.append(cur)
        pid = cur["parent_component_id"]
        cur = by_id.get(pid) if pid else None
    eff = Decimal("1.0")
    for c in chain:  # order irrelevant for a product
        own = Decimal("1.0") if c["component_type"] == "PACKAGING" else c["scale_exponent"]
        eff *= own
    return eff


@bp.route("/plant/recipes/<recipeId>/scale-preview", methods=["GET"])
@endpoint(PLANT_ROLES)
def scale_preview(user_id, role, recipeId):
    recipe = svc.require_record("recipes", recipeId, "Recipe")
    raw_target = request.args.get("target_units")
    if raw_target is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required query parameter: target_units")
    try:
        target = int(raw_target)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'target_units' must be an integer")
    if target <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'target_units' must be > 0")

    raw = Decimal(target) / Decimal(recipe["base_batch_yield_units"])
    scale_factor = min(max(raw, SCALE_MIN), SCALE_MAX)
    comps = _topological_order(recipe["id"])
    by_id = {c["id"]: c for c in svc.components_of_recipe(recipe["id"])}
    lines = []
    for c in comps:
        eff = _effective_exponent(c, by_id)
        qty = q3(c["quantity_per_base_batch"] * (scale_factor ** eff))
        lines.append(
            {
                "component_id": c["id"],
                "component_name": c["component_name"],
                "component_type": c["component_type"],
                "parent_component_id": c["parent_component_id"],
                "unit_of_measure": c["unit_of_measure"],
                "quantity_per_base_batch": fnum(c["quantity_per_base_batch"]),
                "scale_exponent": fnum(c["scale_exponent"]),
                "effective_exponent": fnum(eff),
                "scaled_quantity": fnum(qty),
            }
        )
    return ok_object(
        {
            "target_units": target,
            "scale_factor": fnum(scale_factor),
            "lines": lines,
        }
    )
