"""Ingredient lots: receipt, release, expiry and the depth-6 recall cascade."""

from flask import Blueprint

import config
from db import DB, base_record, touch
from errors import ApiError
from ladder import endpoint
from response import created, ok
from routes.common import list_endpoint
from serialize import dump
from services import cascade
from services.gates import require_state
from tsutil import gte, lt, ts_input

bp = Blueprint("lots", __name__)

ADMIN = config.ROLE_ADMIN
BAKER = config.ROLE_BAKER
INSPECTOR = config.ROLE_INSPECTOR


@bp.post("/bakery/ingredient-lots")
@endpoint(roles=[BAKER])
def create_lot(ctx):
    fks = ctx.body_fks(required=("baker_id",))          # rung 10
    baker = fks["baker_id"]
    if baker is None:
        raise ApiError("ERR_VALIDATION", "baker_id is required.")
    ctx.ownership(baker_id=baker["id"])                 # rung 12
    lot_code = ctx.req_str("lot_code")                  # rung 13
    received_at = ctx.req_dt("received_at")
    expires_at = ctx.req_dt("expires_at")
    allergens = ctx.opt_list("allergens", [])
    cross = ctx.opt_list("cross_contact_allergens", [])
    for arr, label in ((allergens, "allergens"),
                       (cross, "cross_contact_allergens")):
        for a in arr:
            if not isinstance(a, str):
                raise ApiError("ERR_VALIDATION",
                               "%s entries must be strings." % label)

    rec = base_record(ctx.now)
    rec.update({
        "baker_id": baker["id"],
        "lot_code": lot_code,
        "allergens": list(allergens),
        "cross_contact_allergens": list(cross),
        "lot_status": "RECEIVED",
        "received_at": ts_input(received_at),
        "expires_at": ts_input(expires_at),
    })
    DB.coll("ingredient_lots")[rec["id"]] = rec
    return created(dump("ingredient_lots", rec))


@bp.post("/bakery/ingredient-lots/<ingredient_lot_id>/release")
@endpoint(roles=[BAKER], path=("ingredient_lot_id",))
def release_lot(ctx):
    lot = ctx.p["ingredient_lot_id"]
    ctx.ownership(baker_id=lot.get("baker_id"))              # rung 12
    force = ctx.opt_bool("force_expiry_check", False)        # rung 13
    current = lot.get("lot_status")
    require_state(current, ("RECEIVED", "RELEASED"), "lot_status")   # rung 19
    expires = lot.get("expires_at")
    if current == "RECEIVED":
        # release requires the clock strictly before expiry
        if expires is None or not lt(ctx.now, expires):
            # Adjudication of friction 2: ERR_INVALID_STATE
            raise ApiError("ERR_INVALID_STATE",
                           "The lot may not be released at or after its expiry.")
        lot["lot_status"] = "RELEASED"
    else:
        # the second, distinct behaviour of the same capability
        if not force:
            raise ApiError("ERR_INVALID_STATE",
                           "A RELEASED lot only moves to EXPIRED with "
                           "force_expiry_check true.")
        if expires is None or not gte(ctx.now, expires):
            raise ApiError("ERR_INVALID_STATE",
                           "The lot has not yet reached its expiry instant.")
        lot["lot_status"] = "EXPIRED"
    touch(lot, ctx.now)
    return ok(dump("ingredient_lots", lot))


@bp.post("/bakery/ingredient-lots/<ingredient_lot_id>/recall")
@endpoint(roles=[ADMIN], path=("ingredient_lot_id",))
def recall_lot(ctx):
    # CARVE-OUT: rung 15 never applies here, so a recall stays reachable while
    # the operator's permit is suspended.
    lot = ctx.p["ingredient_lot_id"]
    if ctx.body.get("recall_reason") is None:                # rung 13
        raise ApiError("ERR_VALIDATION", "recall_reason is required.")
    ctx.req_str("recall_reason")
    require_state(lot.get("lot_status"),                      # rung 19
                  ("RECEIVED", "RELEASED", "CONSUMED"), "lot_status")
    lot["lot_status"] = "RECALLED"
    touch(lot, ctx.now)
    cascade.recall_lot(lot, ctx.now)
    return ok(dump("ingredient_lots", lot))


@bp.get("/bakery/ingredient-lots/<ingredient_lot_id>")
@endpoint(roles=[BAKER, ADMIN, INSPECTOR], path=("ingredient_lot_id",))
def read_lot(ctx):
    lot = ctx.p["ingredient_lot_id"]
    ctx.ownership(baker_id=lot.get("baker_id"))
    return ok(dump("ingredient_lots", lot))


@bp.get("/bakery/ingredient-lots")
@endpoint(roles=[BAKER, ADMIN, INSPECTOR], list_ep=True)
def list_lots(ctx):
    return list_endpoint(ctx, "ingredient_lots", {
        "baker_id": "baker_id",
        "lot_status": "lot_status",
        "lot_code": "lot_code",
    })
