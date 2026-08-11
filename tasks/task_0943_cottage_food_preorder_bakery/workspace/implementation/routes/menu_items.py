"""Menu items: the sellable face of a recipe, and the listing posture."""

from flask import Blueprint

import config
from db import DB, base_record, touch
from errors import ApiError
from ladder import endpoint
from response import created, ok
from routes.common import list_endpoint
from serialize import dump
from services import allergen
from services.gates import (permit_gate, product_class_gate,
                            recipe_published_gate, require_state)

bp = Blueprint("menu_items", __name__)

ADMIN = config.ROLE_ADMIN
BAKER = config.ROLE_BAKER
CUSTOMER = config.ROLE_CUSTOMER
INSPECTOR = config.ROLE_INSPECTOR


@bp.post("/bakery/menu-items")
@endpoint(roles=[BAKER])
def create_menu_item(ctx):
    fks = ctx.body_fks(required=("baker_id", "recipe_id"))     # rung 10
    baker = fks["baker_id"]
    recipe = fks["recipe_id"]
    if baker is None:
        raise ApiError("ERR_VALIDATION", "baker_id is required.")
    if recipe is None:
        raise ApiError("ERR_VALIDATION", "recipe_id is required.")
    ctx.ownership(baker_id=baker["id"])                        # rung 12
    # rung 13
    name = ctx.req_str("name")
    if ctx.body.get("product_class") is None:
        raise ApiError("ERR_VALIDATION", "product_class is required.")
    if ctx.body.get("pricing_basis") is None:
        raise ApiError("ERR_VALIDATION", "pricing_basis is required.")
    unit_price_cents = ctx.req_int("unit_price_cents", minimum=0)
    dozen_price_cents = ctx.req_int("dozen_price_cents", minimum=0)
    temp_sensitive = ctx.opt_bool("temp_sensitive", False)
    oven_hours_per_batch = ctx.opt_num("oven_hours_per_batch",
                                       config.OVEN_HOURS_PER_BATCH_SLOT)
    yield_units_per_slot = ctx.opt_int("yield_units_per_slot",
                                       config.DEFAULT_YIELD_UNITS_PER_SLOT,
                                       minimum=0)
    # rung 14
    product_class = ctx.enum("product_class", "product_class")
    pricing_basis = ctx.enum("pricing_basis", "pricing_basis")
    oven_profile = ctx.enum("oven_profile", "oven_profile",
                            required=False, default="STANDARD")
    # rung 15
    permit_gate(baker)

    rec = base_record(ctx.now)
    rec.update({
        "baker_id": baker["id"],
        "recipe_id": recipe["id"],
        "name": name,
        "product_class": product_class,
        "pricing_basis": pricing_basis,
        "unit_price_cents": unit_price_cents,
        "dozen_price_cents": dozen_price_cents,
        "temp_sensitive": temp_sensitive,
        "oven_profile": oven_profile,
        "oven_hours_per_batch": oven_hours_per_batch,
        "yield_units_per_slot": yield_units_per_slot,
        "listing_status": "DRAFT",
        "rating_avg": None,
        "rating_count": 0,
        "allergen_summary": [],
    })
    DB.coll("menu_items")[rec["id"]] = rec
    return created(dump("menu_items", rec))


@bp.post("/bakery/menu-items/<menu_item_id>/listing-status")
@endpoint(roles=[BAKER], path=("menu_item_id",))
def listing_status(ctx):
    item = ctx.p["menu_item_id"]
    ctx.ownership(baker_id=item.get("baker_id"))              # rung 12
    if ctx.body.get("to_status") is None:                      # rung 13
        raise ApiError("ERR_VALIDATION", "to_status is required.")
    to_status = ctx.enum("to_status", "listing_status")        # rung 14
    baker = DB.get("bakers", item.get("baker_id"))
    permit_gate(baker)                                         # rung 15
    current = item.get("listing_status")
    # rung 19
    if to_status == "LISTED":
        require_state(current, ("DRAFT", "PAUSED"), "listing_status")
    elif to_status == "PAUSED":
        require_state(current, ("LISTED",), "listing_status")
    elif to_status == "DELISTED":
        require_state(current, ("LISTED", "PAUSED"), "listing_status")
    else:
        raise ApiError("ERR_INVALID_STATE",
                       "%s is not reachable through this capability." % to_status)

    # Adjudication of friction 7: NARROW reading -- rungs 25 and 26 guard only
    # transitions INTO LISTED.  Under the broad reading an item whose backing
    # recipe later left PUBLISHED could not even be paused or delisted, and
    # since a recipe may only be RETIRED while no item backed by it is LISTED,
    # the recipe's REVISING -> RETIRED transition would become unreachable
    # exactly when an item is listed.  The narrow reading strands nothing.
    if to_status == "LISTED":
        product_class_gate(item)                               # rung 25
        recipe_published_gate(DB.get("recipes", item.get("recipe_id")))  # rung 26

    item["listing_status"] = to_status
    if to_status == "LISTED":
        item["allergen_summary"] = allergen.union_only(item.get("recipe_id"))
    touch(item, ctx.now)
    return ok(dump("menu_items", item))


@bp.get("/bakery/menu-items/<menu_item_id>")
@endpoint(roles=[BAKER, CUSTOMER, ADMIN, INSPECTOR], path=("menu_item_id",))
def read_menu_item(ctx):
    item = ctx.p["menu_item_id"]
    ctx.ownership(baker_id=item.get("baker_id"))
    return ok(dump("menu_items", item))


@bp.get("/bakery/menu-items")
@endpoint(roles=[BAKER, CUSTOMER, ADMIN, INSPECTOR], list_ep=True)
def list_menu_items(ctx):
    return list_endpoint(ctx, "menu_items", {
        "baker_id": "baker_id",
        "recipe_id": "recipe_id",
        "listing_status": "listing_status",
        "product_class": "product_class",
    })
