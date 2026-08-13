"""IngredientIndex endpoints."""

from flask import Blueprint, request

from db import DB
from middleware import get_auth, require_role
from helpers import (
    body, req_string, req_enum, req_number, parse_period, make_entity, touch,
    lookup, list_response, public,
)
from response import success_object
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE

bp = Blueprint("ingredient_indices", __name__)


@bp.route("/bakery/ingredient-indices", methods=["POST"])
def create_index():
    _, role = get_auth()
    require_role(role, {"PricingAnalyst"})
    data = body()
    plant_id = req_string(data, "plant_id")
    lookup(DB.plants, plant_id, "plant")
    ingredient = req_enum(data, "ingredient", {"FLOUR", "BUTTER"})
    period = req_string(data, "period")
    parse_period(period, "period")
    forecast_value = req_number(data, "forecast_value")

    for ix in DB.ingredient_indices.values():
        if (
            ix.get("plant_id") == plant_id
            and ix.get("ingredient") == ingredient
            and ix.get("period") == period
        ):
            raise ApiError(ERR_INVALID_REQUEST, "Index already exists for (plant, ingredient, period)", 400)

    index = make_entity({
        "plant_id": plant_id,
        "ingredient": ingredient,
        "period": period,
        "forecast_value": forecast_value,
        "published_value": None,
        "status": "FORECAST",
    })
    DB.ingredient_indices[index["id"]] = index
    return success_object(public(index), status=201)


@bp.route("/bakery/ingredient-indices/<iid>", methods=["GET"])
def get_index(iid):
    get_auth()
    index = lookup(DB.ingredient_indices, iid, "ingredient index")
    return success_object(public(index))


@bp.route("/bakery/ingredient-indices", methods=["GET"])
def list_indices():
    get_auth()
    filters = {
        "plant_id": request.args.get("plant_id"),
        "ingredient": request.args.get("ingredient"),
        "period": request.args.get("period"),
    }
    return list_response(list(DB.ingredient_indices.values()), filters)


@bp.route("/bakery/ingredient-indices/<iid>/publish", methods=["POST"])
def publish_index(iid):
    _, role = get_auth()
    require_role(role, {"PricingAnalyst"})
    index = lookup(DB.ingredient_indices, iid, "ingredient index")
    data = body()
    published_value = req_number(data, "published_value")
    if index.get("status") != "FORECAST":
        raise ApiError(ERR_INVALID_STATE, "Index is not FORECAST", 409)
    index["published_value"] = published_value
    index["status"] = "PUBLISHED"
    touch(index)

    from services.cascades import cascade_index_published
    cascade_index_published(index)

    return success_object(public(index))
