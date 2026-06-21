"""Ingredient catalogue and ingredient-scoped reverse lookups."""
from flask import Blueprint, request

from db import db, LOCK
from errors import ApiError
from middleware import get_identity, require_roles, get_json_body, parse_pagination
from response import success, paginated
from services.common import (
    stamp_new, public, get_or_404, sorted_by_creation, paginate,
    require_fields, as_int,
)

bp = Blueprint("ingredients", __name__)


@bp.post("/ingredients")
def create_ingredient():
    _, role = get_identity()
    require_roles(role, {"FacilityManager"})
    body = get_json_body()
    require_fields(body, ["name", "unit_cost_cents"])
    if not isinstance(body["name"], str) or not body["name"]:
        raise ApiError("ERR_INVALID_REQUEST")
    unit_cost = as_int(body["unit_cost_cents"])
    if unit_cost < 0:
        raise ApiError("ERR_INVALID_REQUEST")
    allergen_tags = body.get("allergen_tags", [])
    if allergen_tags is None:
        allergen_tags = []
    if not isinstance(allergen_tags, list):
        raise ApiError("ERR_INVALID_REQUEST")
    with LOCK:
        ingredient = {
            "name": body["name"],
            "unit_cost_cents": unit_cost,
            "on_hand_qty": 0,
            "allergen_tags": list(allergen_tags),
        }
        stamp_new(ingredient)
        db.ingredients[ingredient["id"]] = ingredient
        return success(public(ingredient), 201)


@bp.get("/ingredients")
def list_ingredients():
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    limit, offset = parse_pagination()
    with LOCK:
        records = sorted_by_creation(list(db.ingredients.values()))
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)


@bp.get("/ingredients/<ingredient_id>")
def get_ingredient(ingredient_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    with LOCK:
        ingredient = get_or_404(db.ingredients, ingredient_id)
        return success(public(ingredient))


@bp.get("/ingredients/<ingredient_id>/recipe-components")
def list_ingredient_recipe_components(ingredient_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    limit, offset = parse_pagination()
    with LOCK:
        get_or_404(db.ingredients, ingredient_id)
        records = [c for c in db.recipe_components.values() if c["ingredient_id"] == ingredient_id]
        records = sorted_by_creation(records)
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)


@bp.get("/ingredients/<ingredient_id>/ingredient-orders")
def list_ingredient_orders_for_ingredient(ingredient_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    with LOCK:
        get_or_404(db.ingredients, ingredient_id)
        records = [o for o in db.ingredient_orders.values() if o["ingredient_id"] == ingredient_id]
        records = sorted_by_creation(records)
        if status:
            records = [o for o in records if o["status"] == status]
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)
