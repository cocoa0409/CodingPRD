"""Recipe endpoints (PRD §3.3)."""
from flask import Blueprint

import serialize
from db import db, stamp_create, touch
from errors import invalid_state
from middleware import require_roles
from response import object_response, array_response
from routes.lookup import get_recipe, get_product
from services.product import line_cost, recompute_recipe_cost
from validate import get_json_body, require, as_str, as_number, parse_pagination, paginate

bp = Blueprint("recipes", __name__)


@bp.route("/recipes", methods=["POST"])
@require_roles("BarManager")
def create_recipe():
    body = get_json_body()
    name = as_str(require(body, "name"), "name")
    record = {
        "name": name,
        "recipe_cost_cents": 0,
        "status": "DRAFT",
    }
    stamp_create(record)
    db.recipes[record["id"]] = record
    return object_response(serialize.recipe(record), 201)


@bp.route("/recipes/<rid>", methods=["GET"])
@require_roles("BarManager", "InventoryManager")
def read_recipe(rid):
    r = get_recipe(rid)
    return object_response(serialize.recipe(r))


@bp.route("/recipes/<rid>/lines", methods=["POST"])
@require_roles("BarManager")
def add_recipe_line(rid):
    recipe = get_recipe(rid)
    body = get_json_body()
    product_id = require(body, "product_id")
    pour_ml = as_number(require(body, "pour_ml"), "pour_ml", gt=0)
    # body FK existence (404)
    product = get_product(product_id)
    # state: lines may only be added while DRAFT
    if recipe["status"] != "DRAFT":
        raise invalid_state("Recipe lines may only be added to a DRAFT recipe.")

    record = {
        "recipe_id": rid,
        "product_id": product_id,
        "pour_ml": pour_ml,
        "line_cost_cents": line_cost(product, pour_ml),
    }
    stamp_create(record)
    db.recipe_lines[record["id"]] = record
    # recompute recipe cost (round-per-line then sum)
    recompute_recipe_cost(recipe)
    return object_response(serialize.recipe_line(record), 201)


@bp.route("/recipes/<rid>/lines", methods=["GET"])
@require_roles("BarManager", "InventoryManager")
def list_recipe_lines(rid):
    get_recipe(rid)
    limit, offset = parse_pagination()
    items = [r for r in db.recipe_lines.values() if r["recipe_id"] == rid]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.recipe_line(r) for r in page], limit, offset, total)


def _active_menu_item_references(recipe_id):
    for mi in db.menu_items.values():
        if mi["recipe_id"] == recipe_id and mi["status"] == "ACTIVE":
            return True
    return False


@bp.route("/recipes/<rid>/publish", methods=["POST"])
@require_roles("BarManager")
def publish_recipe(rid):
    recipe = get_recipe(rid)
    if recipe["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT recipe can be published.")
    lines = [rl for rl in db.recipe_lines.values() if rl["recipe_id"] == rid]
    if len(lines) < 1:
        raise invalid_state("A recipe must have at least one line to publish.")
    for rl in lines:
        product = db.products.get(rl["product_id"])
        if product is None or product["status"] != "ACTIVE":
            raise invalid_state("Every recipe line product must be ACTIVE to publish.")
    # recompute_recipe_cost (also bumps version via touch)
    recompute_recipe_cost(recipe)
    recipe["status"] = "PUBLISHED"
    touch(recipe)
    return object_response(serialize.recipe(recipe))


@bp.route("/recipes/<rid>/revise", methods=["POST"])
@require_roles("BarManager")
def revise_recipe(rid):
    recipe = get_recipe(rid)
    if recipe["status"] != "PUBLISHED":
        raise invalid_state("Only a PUBLISHED recipe can be revised.")
    if _active_menu_item_references(rid):
        raise invalid_state("Cannot revise a recipe referenced by an ACTIVE menu item.")
    recipe["status"] = "DRAFT"
    touch(recipe)
    return object_response(serialize.recipe(recipe))


@bp.route("/recipes/<rid>/retire", methods=["POST"])
@require_roles("BarManager")
def retire_recipe(rid):
    recipe = get_recipe(rid)
    if recipe["status"] != "PUBLISHED":
        raise invalid_state("Only a PUBLISHED recipe can be retired.")
    if _active_menu_item_references(rid):
        raise invalid_state("Cannot retire a recipe referenced by an ACTIVE menu item.")
    recipe["status"] = "RETIRED"
    touch(recipe)
    return object_response(serialize.recipe(recipe))
