"""Ingredient endpoints."""

from flask import Blueprint, request

import errors
from db import store
from middleware import (require_roles, get_json_body, require_string,
                        require_enum, optional_bool, parse_pagination, paginate)
from response import success_object, success_list
from services.calculations import stamp_new, serialize, serialize_list

bp = Blueprint("ingredients", __name__)

ALLERGEN_CLASSES = {"NONE", "POULTRY", "BEEF", "FISH", "DAIRY", "GRAIN", "OTHER"}


@bp.route("/ingredients", methods=["POST"])
def create_ingredient():
    require_roles("FormulationScientist")
    body = get_json_body()
    aafco_name = require_string(body, "aafco_name")
    ingredient_code = require_string(body, "ingredient_code")
    if len(ingredient_code) != 8 or not ingredient_code.isalnum() or ingredient_code.upper() != ingredient_code:
        raise errors.invalid_request("ingredient_code must be 8 uppercase alphanumeric chars")
    nutrient_matrix = body.get("nutrient_matrix")
    if not isinstance(nutrient_matrix, dict):
        raise errors.invalid_request("nutrient_matrix must be an object")
    if "MOISTURE" not in nutrient_matrix:
        raise errors.invalid_request("nutrient_matrix must include MOISTURE")
    allergen_class = require_enum(body, "allergen_class", ALLERGEN_CLASSES)
    requires_coa = optional_bool(body, "requires_coa", True)

    for ing in store.ingredients.values():
        if ing["aafco_name"] == aafco_name:
            raise errors.duplicate_key("aafco_name already exists")
        if ing["ingredient_code"] == ingredient_code:
            raise errors.duplicate_key("ingredient_code already exists")

    ing = {
        "aafco_name": aafco_name,
        "ingredient_code": ingredient_code,
        "nutrient_matrix": nutrient_matrix,
        "allergen_class": allergen_class,
        "requires_coa": requires_coa,
        "status": "ACTIVE",
    }
    stamp_new(ing)
    store.ingredients[ing["id"]] = ing
    return success_object(serialize(ing), 201)


@bp.route("/ingredients/<id>", methods=["GET"])
def get_ingredient(id):
    require_roles("PlatformAdmin", "FormulationScientist", "QualityAnalyst",
                  "QAApprover", "ProductionPlanner")
    ing = store.ingredients.get(id)
    if ing is None:
        raise errors.not_found("Ingredient not found")
    return success_object(serialize(ing), 200)


@bp.route("/ingredients", methods=["GET"])
def list_ingredients():
    require_roles("PlatformAdmin", "FormulationScientist", "QualityAnalyst",
                  "QAApprover", "ProductionPlanner")
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = sorted(store.ingredients.values(),
                   key=lambda e: (e["_created_at_dt"], e["id"]))
    if status_filter is not None:
        items = [i for i in items if i["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total, 200)
