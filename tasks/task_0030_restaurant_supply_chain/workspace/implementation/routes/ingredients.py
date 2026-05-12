"""Ingredients: POST /ingredients."""

from flask import Blueprint

import db
import errors
import helpers
import response
import serializers
from middleware import auth_required
from services import audit


bp = Blueprint("ingredients", __name__, url_prefix="/supply-chain/ingredients")


@bp.route("", methods=["POST"])
@auth_required("CentralKitchenPlanner")
def create_ingredient():
    body = helpers.get_json_body()
    for f in ["sku", "name", "unit", "shelf_life_hours", "unit_cost_cents"]:
        if f not in body:
            errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, f"Missing field: {f}")
    if not isinstance(body["shelf_life_hours"], int) or body["shelf_life_hours"] <= 0:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "shelf_life_hours must be > 0.")
    if not isinstance(body["unit_cost_cents"], int) or body["unit_cost_cents"] < 0:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "unit_cost_cents must be >= 0.")

    iid = db.new_id()
    common = helpers.common_create()
    ing = {
        "id": iid,
        "sku": body["sku"],
        "name": body["name"],
        "unit": body["unit"],
        "shelf_life_hours": body["shelf_life_hours"],
        "unit_cost_cents": body["unit_cost_cents"],
        **common,
    }
    db.ingredients[iid] = ing
    audit.append(target_type="Ingredient", target_id=iid, action="CREATE_INGREDIENT",
                 payload={"sku": ing["sku"]})
    return response.created(serializers.ingredient_dict(ing))
