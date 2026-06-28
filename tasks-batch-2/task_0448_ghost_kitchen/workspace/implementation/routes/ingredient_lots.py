"""IngredientLot endpoints (PRD §3.4)."""
from flask import Blueprint

import errors
from db import store
from middleware import get_identity, require_role
from response import object_response
from services.common import new_entity, serialize, get_or_404
from services import inventory
from validation import get_body, require_str, require_int

bp = Blueprint("ingredient_lots", __name__)


def _check_stall_owner(role, user_id, stall_id):
    if role == "StallOperator" and user_id != stall_id:
        raise errors.forbidden()


@bp.route("/ingredient-lots", methods=["POST"])
def create_lot():
    user_id, role = get_identity()
    require_role(role, ["StallOperator"])
    body = get_body()
    stall_id = require_str(body, "stall_id")
    ingredient_name = require_str(body, "ingredient_name")
    received_at = require_str(body, "received_at")
    unit_cost = require_int(body, "unit_cost_cents_per_gram")
    grams_received = require_int(body, "grams_received")
    with store.lock:
        get_or_404(store.stalls, stall_id)
        # Ownership: operator must own the holding stall.
        _check_stall_owner(role, user_id, stall_id)
        if unit_cost < 0:
            raise errors.invalid_request("unit_cost_cents_per_gram must be >= 0.")
        if grams_received <= 0:
            raise errors.invalid_request("grams_received must be > 0.")
        rec = new_entity("IngredientLot", {
            "stall_id": stall_id,
            "ingredient_name": ingredient_name,
            "received_at": received_at,
            "unit_cost_cents_per_gram": unit_cost,
            "grams_received": grams_received,
            "grams_remaining": grams_received,
        })
        store.ingredient_lots[rec["id"]] = rec
        # Re-evaluate availability: SOLD_OUT items using this ingredient at this
        # stall may flip back to AVAILABLE now that supply was added.
        inventory.reevaluate_for_ingredient(ingredient_name, stall_id)
        return object_response(serialize(rec), 201)


@bp.route("/ingredient-lots/<lid>", methods=["GET"])
def get_lot(lid):
    user_id, role = get_identity()
    require_role(role, ["PlatformOps", "StallOperator"])
    with store.lock:
        rec = get_or_404(store.ingredient_lots, lid)
        return object_response(serialize(rec))
