"""Recipe lifecycle (DRAFT/PUBLISHED/RETIRED), components, and food-cost estimate."""
from flask import Blueprint, request

from db import db, LOCK
from errors import ApiError
from middleware import (
    get_identity, require_roles, require_owner, get_json_body, parse_pagination,
)
from response import success, paginated
from services.common import (
    stamp_new, stamp_new_append_only, touch_no_version, public, find_member,
    get_or_404, sorted_by_creation, paginate, require_fields, as_int, as_number,
)
from services.calculations import estimated_food_cost

bp = Blueprint("recipes", __name__)


def _components_for(recipe_id):
    comps = [c for c in db.recipe_components.values() if c["recipe_id"] == recipe_id]
    return sorted(comps, key=lambda c: c["_seq"])


def _load_member_recipe(member_id, recipe_id):
    find_member(member_id)
    recipe = get_or_404(db.recipes, recipe_id)
    if recipe["member_id"] != member_id:
        raise ApiError("ERR_NOT_FOUND")
    return recipe


@bp.post("/members/<member_id>/recipes")
def create_recipe(member_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator"})
    require_owner(role, user_id, member_id)
    body = get_json_body()
    with LOCK:
        find_member(member_id)
        require_fields(body, ["name", "batch_yield_units"])
        if not isinstance(body["name"], str) or not body["name"]:
            raise ApiError("ERR_INVALID_REQUEST")
        batch_yield = as_int(body["batch_yield_units"])
        if batch_yield < 1:
            raise ApiError("ERR_INVALID_REQUEST")
        recipe = {
            "member_id": member_id,
            "name": body["name"],
            "version": 1,
            "batch_yield_units": batch_yield,
            "allergen_tags": [],
            "estimated_food_cost_cents": 0,
            "status": "DRAFT",
        }
        stamp_new(recipe)
        # Recipe.version is the recipe revision number, seeded at 1 by stamp_new.
        db.recipes[recipe["id"]] = recipe
        return success(public(recipe), 201)


@bp.get("/members/<member_id>/recipes")
def list_member_recipes(member_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    with LOCK:
        find_member(member_id)
        records = [r for r in db.recipes.values() if r["member_id"] == member_id]
        records = sorted_by_creation(records)
        if status:
            records = [r for r in records if r["status"] == status]
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)


@bp.get("/members/<member_id>/recipes/<recipe_id>")
def get_member_recipe(member_id, recipe_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    with LOCK:
        recipe = _load_member_recipe(member_id, recipe_id)
        return success(public(recipe))


@bp.post("/members/<member_id>/recipes/<recipe_id>/components")
def add_recipe_component(member_id, recipe_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator"})
    require_owner(role, user_id, member_id)
    body = get_json_body()
    with LOCK:
        recipe = _load_member_recipe(member_id, recipe_id)
        require_fields(body, ["ingredient_id", "planned_qty"])
        ingredient = get_or_404(db.ingredients, body["ingredient_id"])
        planned_qty = as_number(body["planned_qty"])
        if planned_qty <= 0:
            raise ApiError("ERR_INVALID_REQUEST")
        if recipe["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE")
        component = {
            "recipe_id": recipe_id,
            "ingredient_id": ingredient["id"],
            "planned_qty": planned_qty,
        }
        stamp_new_append_only(component)
        db.recipe_components[component["id"]] = component
        return success(public(component), 201)


@bp.get("/members/<member_id>/recipes/<recipe_id>/components")
def list_recipe_components(member_id, recipe_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    limit, offset = parse_pagination()
    with LOCK:
        _load_member_recipe(member_id, recipe_id)
        records = _components_for(recipe_id)
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)


@bp.post("/members/<member_id>/recipes/<recipe_id>/publish")
def publish_recipe(member_id, recipe_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator"})
    require_owner(role, user_id, member_id)
    with LOCK:
        recipe = _load_member_recipe(member_id, recipe_id)
        if recipe["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE")
        comps = _components_for(recipe_id)
        if not comps:
            raise ApiError("ERR_RECIPE_EMPTY")
        # Allergen union over component ingredients (de-duplicated, stable order).
        tags = []
        for c in comps:
            ing = db.ingredients[c["ingredient_id"]]
            for tag in ing.get("allergen_tags", []):
                if tag not in tags:
                    tags.append(tag)
        cost_by_id = {c["ingredient_id"]: db.ingredients[c["ingredient_id"]]["unit_cost_cents"]
                      for c in comps}
        recipe["allergen_tags"] = tags
        recipe["estimated_food_cost_cents"] = estimated_food_cost(comps, cost_by_id, 1)
        recipe["status"] = "PUBLISHED"
        touch_no_version(recipe)
        return success(public(recipe))


@bp.post("/members/<member_id>/recipes/<recipe_id>/revise")
def revise_recipe(member_id, recipe_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator"})
    require_owner(role, user_id, member_id)
    with LOCK:
        recipe = _load_member_recipe(member_id, recipe_id)
        if recipe["status"] != "PUBLISHED":
            raise ApiError("ERR_INVALID_STATE")
        # No IN_PRODUCTION batch pins this recipe version.
        for b in db.production_batches.values():
            if (b["recipe_id"] == recipe_id and b["status"] == "IN_PRODUCTION"
                    and b["recipe_version_pinned"] == recipe["version"]):
                raise ApiError("ERR_RECIPE_IN_USE")
        recipe["status"] = "DRAFT"
        recipe["version"] += 1
        touch_no_version(recipe)
        return success(public(recipe))


@bp.post("/members/<member_id>/recipes/<recipe_id>/retire")
def retire_recipe(member_id, recipe_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator"})
    require_owner(role, user_id, member_id)
    with LOCK:
        recipe = _load_member_recipe(member_id, recipe_id)
        if recipe["status"] != "PUBLISHED":
            raise ApiError("ERR_INVALID_STATE")
        for b in db.production_batches.values():
            if b["recipe_id"] == recipe_id and b["status"] in ("PLANNED", "IN_PRODUCTION"):
                raise ApiError("ERR_RECIPE_IN_USE")
        recipe["status"] = "RETIRED"
        touch_no_version(recipe)
        return success(public(recipe))


@bp.get("/members/<member_id>/recipes/<recipe_id>/batches")
def list_recipe_batches(member_id, recipe_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    with LOCK:
        _load_member_recipe(member_id, recipe_id)
        records = [b for b in db.production_batches.values() if b["recipe_id"] == recipe_id]
        records = sorted_by_creation(records)
        if status:
            records = [b for b in records if b["status"] == status]
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)
