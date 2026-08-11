"""Batches: mixing, baking, yield confirmation -- and cottage-food labels."""

from flask import Blueprint

import config
from db import DB, base_record, touch
from errors import ApiError
from ladder import endpoint
from response import created, ok
from routes.common import list_endpoint
from serialize import dump
from services import allergen, cascade
from services.gates import recipe_published_gate, require_state

bp = Blueprint("batches", __name__)

ADMIN = config.ROLE_ADMIN
BAKER = config.ROLE_BAKER
CUSTOMER = config.ROLE_CUSTOMER
INSPECTOR = config.ROLE_INSPECTOR


def _baker_of_batch(batch):
    window = DB.get("offer_windows", batch.get("offer_window_id"))
    return (window or {}).get("baker_id")


@bp.post("/bakery/batches/<batch_id>/advance")
@endpoint(roles=[BAKER], path=("batch_id",))
def advance_batch(ctx):
    # CARVE-OUT: rung 16 never applies -- batch work is legal only once LOCKED.
    batch = ctx.p["batch_id"]
    ctx.ownership(baker_id=_baker_of_batch(batch))                  # rung 12
    if ctx.body.get("to_status") is None:                            # rung 13
        raise ApiError("ERR_VALIDATION", "to_status is required.")
    to_status = ctx.enum("to_status", "batch_status")                # rung 14
    window = DB.get("offer_windows", batch.get("offer_window_id"))

    if to_status == "MIXED":                                         # rung 19
        require_state(batch.get("batch_status"), ("PLANNED",), "batch_status")
        if (window or {}).get("window_status") != "IN_PRODUCTION":
            raise ApiError("ERR_INVALID_STATE",
                           "Mixing requires an IN_PRODUCTION window.")
        if allergen.closure_recalled(batch.get("recipe_id")):        # rung 27
            raise ApiError("ERR_LOT_RECALLED",
                           "A component of this batch's recipe tree is recalled.")
        batch["batch_status"] = "MIXED"
        touch(batch, ctx.now)
    elif to_status == "BAKED":
        require_state(batch.get("batch_status"), ("MIXED",), "batch_status")
        if allergen.closure_recalled(batch.get("recipe_id")):        # rung 27
            raise ApiError("ERR_LOT_RECALLED",
                           "A component of this batch's recipe tree is recalled.")
        batch["batch_status"] = "BAKED"
        # physical stock is spent: RELEASED lots in the tree become CONSUMED
        try:
            _a, _d, lots, _c = allergen.profile(batch.get("recipe_id"))
        except ApiError:
            lots = []
        seen = set()
        for lot in lots:
            if lot["id"] in seen:
                continue
            seen.add(lot["id"])
            if lot.get("lot_status") == "RELEASED":
                lot["lot_status"] = "CONSUMED"
                touch(lot, ctx.now)
        touch(batch, ctx.now)
    else:
        raise ApiError("ERR_INVALID_STATE",
                       "%s is not reachable through this capability." % to_status)
    return ok(dump("batches", batch))


@bp.post("/bakery/batches/<batch_id>/confirm-yield")
@endpoint(roles=[BAKER], path=("batch_id",))
def confirm_yield(ctx):
    batch = ctx.p["batch_id"]
    ctx.ownership(baker_id=_baker_of_batch(batch))                  # rung 12
    actual = ctx.req_int("actual_yield_units", minimum=0)            # rung 13
    # rung 19 CARVE-OUT: the batch-state precondition is owned exclusively by
    # rung 36 so that ERR_BATCH_NOT_BAKED stays reachable.
    if batch.get("batch_status") != "BAKED":                         # rung 36
        raise ApiError("ERR_BATCH_NOT_BAKED",
                       "The batch is %s." % batch.get("batch_status"))
    cascade.allocate_yield(batch, actual, ctx.now)
    return ok(dump("batches", batch))


@bp.get("/bakery/batches/<batch_id>")
@endpoint(roles=[BAKER, ADMIN, INSPECTOR], path=("batch_id",))
def read_batch(ctx):
    batch = ctx.p["batch_id"]
    ctx.ownership(baker_id=_baker_of_batch(batch))
    return ok(dump("batches", batch))


@bp.get("/bakery/batches")
@endpoint(roles=[BAKER, ADMIN, INSPECTOR], list_ep=True)
def list_batches(ctx):
    return list_endpoint(ctx, "batches", {
        "offer_window_id": "offer_window_id",
        "menu_item_id": "menu_item_id",
        "recipe_id": "recipe_id",
        "batch_status": "batch_status",
    })


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

@bp.post("/bakery/labels")
@endpoint(roles=[BAKER])
def issue_label(ctx):
    # rung 10: order_line_id then recipe_id, alphabetically.  A body
    # order_line_id gives ERR_RESOURCE_NOT_FOUND -- rung 6's ERR_ORDER_NOT_FOUND
    # covers PATH segments only.
    fks = ctx.body_fks(required=("order_line_id", "recipe_id"))
    line = fks["order_line_id"]
    recipe = fks["recipe_id"]
    if line is None:
        raise ApiError("ERR_VALIDATION", "order_line_id is required.")
    if recipe is None:
        raise ApiError("ERR_VALIDATION", "recipe_id is required.")
    ctx.ownership(baker_id=recipe.get("baker_id"))                   # rung 12
    net_weight_grams = ctx.req_num("net_weight_grams")               # rung 13
    expected = ctx.req_int("expected_recipe_version", minimum=0)
    if expected != recipe.get("version"):                            # rung 22
        raise ApiError("ERR_STALE_RECIPE_VERSION",
                       "expected_recipe_version is stale.")
    recipe_published_gate(recipe)                                    # rung 26
    if allergen.closure_recalled(recipe["id"]):                      # rung 27
        raise ApiError("ERR_LOT_RECALLED",
                       "The recipe closure contains a recalled component.")

    baker = DB.get("bakers", recipe.get("baker_id"))
    allergens = allergen.union_only(recipe["id"])
    advisory = allergen.advisory_text(recipe["id"], baker)
    statement = config.COTTAGE_FOOD_STATEMENT_TEXT
    if allergens:
        statement = statement + " Contains: " + ", ".join(allergens) + "."

    rec = base_record(ctx.now)
    rec.update({
        "order_line_id": line["id"],
        "recipe_id": recipe["id"],
        "recipe_version_pinned": recipe.get("published_version") or 0,
        "label_status": "ISSUED",
        "net_weight_grams": net_weight_grams,
        "allergen_union": allergens,
        "cross_contact_advisory": advisory,
        "statement_text": statement,
    })
    DB.coll("labels")[rec["id"]] = rec
    # Adjudication of friction 1: ISSUANCE BUMPS THE RECIPE'S version.  Both the
    # scaffold's endpoint side-effect list and PRD 3.7 state the increment
    # outright; dropping it would make a declared, observable side effect
    # unreachable.  Keeping it strands nothing -- a client labelling several
    # lines of one order simply re-reads the recipe between calls, which is the
    # consequence PRD 3.7 itself spells out.
    touch(recipe, ctx.now)
    return created(dump("labels", rec))


@bp.get("/bakery/labels/<label_id>")
@endpoint(roles=[BAKER, CUSTOMER, ADMIN, INSPECTOR], path=("label_id",))
def read_label(ctx):
    label = ctx.p["label_id"]
    recipe = DB.get("recipes", label.get("recipe_id"))
    ctx.ownership(baker_id=(recipe or {}).get("baker_id"))
    return ok(dump("labels", label))


@bp.get("/bakery/labels")
@endpoint(roles=[BAKER, CUSTOMER, ADMIN, INSPECTOR], list_ep=True)
def list_labels(ctx):
    return list_endpoint(ctx, "labels", {
        "order_line_id": "order_line_id",
        "recipe_id": "recipe_id",
        "label_status": "label_status",
    })
