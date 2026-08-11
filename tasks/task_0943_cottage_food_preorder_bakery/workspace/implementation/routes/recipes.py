"""Recipes, recipe components, publication and the allergen profile."""

from flask import Blueprint

import config
from db import DB, base_record, touch
from errors import ApiError
from ladder import endpoint
from response import created, ok
from routes.common import list_endpoint
from serialize import dump
from services import allergen, cascade
from services.gates import require_state

bp = Blueprint("recipes", __name__)

ADMIN = config.ROLE_ADMIN
BAKER = config.ROLE_BAKER
CUSTOMER = config.ROLE_CUSTOMER
INSPECTOR = config.ROLE_INSPECTOR


@bp.post("/bakery/recipes")
@endpoint(roles=[BAKER])
def create_recipe(ctx):
    fks = ctx.body_fks(required=("baker_id",))     # rung 10
    baker = fks["baker_id"]
    if baker is None:
        raise ApiError("ERR_VALIDATION", "baker_id is required.")
    ctx.ownership(baker_id=baker["id"])            # rung 12
    name = ctx.req_str("name")                     # rung 13

    rec = base_record(ctx.now)
    rec.update({
        "baker_id": baker["id"],
        "name": name,
        "recipe_status": "DRAFT",
        "published_version": 0,
        "allergen_union": [],
        "tree_depth": 1,
        "cross_contact_advisory": None,
    })
    DB.coll("recipes")[rec["id"]] = rec
    allergen.recompute_recipe(rec)
    return created(dump("recipes", rec))


@bp.post("/bakery/recipes/<recipe_id>/components")
@endpoint(roles=[BAKER], path=("recipe_id",))
def add_component(ctx):
    recipe = ctx.p["recipe_id"]
    # rung 10: remaining body foreign keys, alphabetically
    fks = ctx.body_fks(optional=("ingredient_lot_id", "sub_recipe_id"))
    ctx.ownership(baker_id=recipe.get("baker_id"))         # rung 12
    # rung 13
    component_name = ctx.req_str("component_name")
    quantity_grams = ctx.req_num("quantity_grams")
    declared = ctx.opt_list("declared_allergens", [])
    for a in declared:
        if not isinstance(a, str):
            raise ApiError("ERR_VALIDATION",
                           "declared_allergens entries must be strings.")

    prospective = {
        "recipe_id": recipe["id"],
        "sub_recipe_id": ctx.body.get("sub_recipe_id"),
        "ingredient_lot_id": ctx.body.get("ingredient_lot_id"),
        "component_name": component_name,
        "declared_allergens": list(declared),
        "recalled_component": False,
        "created_at": ctx.now,
        "id": "",
    }
    # rung 27
    lot = fks.get("ingredient_lot_id")
    if lot is not None and lot.get("lot_status") == "RECALLED":
        raise ApiError("ERR_LOT_RECALLED", "The referenced lot is RECALLED.")
    if allergen.closure_recalled(recipe["id"], extra=prospective):
        raise ApiError("ERR_LOT_RECALLED",
                       "The recipe closure contains a recalled component.")
    # rung 28 -- acyclic and no deeper than ALLERGEN_TREE_MAX_DEPTH
    allergen.profile(recipe["id"], extra=prospective)

    rec = base_record(ctx.now)
    rec.update({
        "recipe_id": recipe["id"],
        "sub_recipe_id": ctx.body.get("sub_recipe_id"),
        "ingredient_lot_id": ctx.body.get("ingredient_lot_id"),
        "component_name": component_name,
        "declared_allergens": list(declared),
        "quantity_grams": quantity_grams,
        "recalled_component": False,
    })
    DB.coll("recipe_components")[rec["id"]] = rec
    allergen.recompute_recipe(recipe)
    touch(recipe, ctx.now)
    return created(dump("recipe_components", rec))


@bp.post("/bakery/recipes/<recipe_id>/publish")
@endpoint(roles=[BAKER], path=("recipe_id",))
def publish(ctx):
    recipe = ctx.p["recipe_id"]
    ctx.ownership(baker_id=recipe.get("baker_id"))          # rung 12
    was = recipe.get("recipe_status")
    require_state(was, ("DRAFT", "REVISING"), "recipe_status")   # rung 19
    # rung 27
    if allergen.closure_recalled(recipe["id"]):
        raise ApiError("ERR_LOT_RECALLED",
                       "The recipe closure contains a recalled component.")
    # rung 28
    allergen.profile(recipe["id"])

    recipe["recipe_status"] = "PUBLISHED"
    recipe["published_version"] = (recipe.get("published_version") or 0) + 1
    allergen.recompute_recipe(recipe)
    if was == "REVISING":
        # the three-hop label supersession cascade
        cascade.supersede_labels(recipe, ctx.now)
    else:
        allergen.recompute_menu_item_summaries(recipe["id"])
    touch(recipe, ctx.now)
    return ok(dump("recipes", recipe))


@bp.post("/bakery/recipes/<recipe_id>/lifecycle")
@endpoint(roles=[BAKER], path=("recipe_id",))
def lifecycle(ctx):
    recipe = ctx.p["recipe_id"]
    ctx.ownership(baker_id=recipe.get("baker_id"))
    if ctx.body.get("to_status") is None:                 # rung 13
        raise ApiError("ERR_VALIDATION", "to_status is required.")
    to_status = ctx.enum("to_status", "recipe_status")    # rung 14
    current = recipe.get("recipe_status")
    if to_status == "REVISING":                           # rung 19
        require_state(current, ("PUBLISHED",), "recipe_status")
    elif to_status == "RETIRED":
        require_state(current, ("PUBLISHED", "REVISING"), "recipe_status")
        for item in DB.coll("menu_items").values():
            if (item.get("recipe_id") == recipe["id"]
                    and item.get("listing_status") == "LISTED"):
                # Adjudication of friction 2: ERR_INVALID_STATE, see gates.py
                raise ApiError("ERR_INVALID_STATE",
                               "A menu item backed by this recipe is LISTED.")
    else:
        raise ApiError("ERR_INVALID_STATE",
                       "%s is not reachable through this capability." % to_status)
    recipe["recipe_status"] = to_status
    touch(recipe, ctx.now)
    return ok(dump("recipes", recipe))


@bp.get("/bakery/recipes/<recipe_id>")
@endpoint(roles=[BAKER, ADMIN, INSPECTOR], path=("recipe_id",))
def read_recipe(ctx):
    recipe = ctx.p["recipe_id"]
    ctx.ownership(baker_id=recipe.get("baker_id"))
    return ok(dump("recipes", recipe))


@bp.get("/bakery/recipes")
@endpoint(roles=[BAKER, ADMIN, INSPECTOR], list_ep=True)
def list_recipes(ctx):
    return list_endpoint(ctx, "recipes", {
        "baker_id": "baker_id",
        "recipe_status": "recipe_status",
    })


@bp.get("/bakery/recipes/<recipe_id>/allergen-profile")
@endpoint(roles=[BAKER, ADMIN, INSPECTOR, CUSTOMER], path=("recipe_id",))
def allergen_profile(ctx):
    recipe = ctx.p["recipe_id"]
    ctx.ownership(baker_id=recipe.get("baker_id"))
    baker = DB.get("bakers", recipe.get("baker_id"))
    try:
        allergens, depth, lots, _comps = allergen.profile(recipe["id"])
    except ApiError:
        allergens, depth, lots = [], recipe.get("tree_depth") or 1, []
    applies = bool(baker is not None and baker.get("shared_kitchen"))
    if not applies:
        applies = any(l.get("cross_contact_allergens") for l in lots)
    direct = [c for c in DB.coll("recipe_components").values()
              if c.get("recipe_id") == recipe["id"]]
    return ok({
        "allergen_union": allergens,
        "tree_depth": depth,
        "cross_contact_advisory": (config.CROSS_CONTACT_ADVISORY_TEXT
                                   if applies else None),
        "component_count": len(direct),
        "published_version": recipe.get("published_version") or 0,
    })


@bp.get("/bakery/recipe-components/<recipe_component_id>")
@endpoint(roles=[BAKER, ADMIN, INSPECTOR], path=("recipe_component_id",))
def read_component(ctx):
    comp = ctx.p["recipe_component_id"]
    parent = DB.get("recipes", comp.get("recipe_id"))
    ctx.ownership(baker_id=(parent or {}).get("baker_id"))
    return ok(dump("recipe_components", comp))


@bp.get("/bakery/recipe-components")
@endpoint(roles=[BAKER, ADMIN, INSPECTOR], list_ep=True)
def list_components(ctx):
    return list_endpoint(ctx, "recipe_components", {
        "recipe_id": "recipe_id",
        "sub_recipe_id": "sub_recipe_id",
        "ingredient_lot_id": "ingredient_lot_id",
    })
